"""Real PostgreSQL additive plans, non-mutating previews and source protection."""

from collections import Counter
from dataclasses import FrozenInstanceError
from datetime import date

import psycopg
import pytest

from app.infrastructure.postgresql.pool import OperatorDatabase
from app.infrastructure.postgresql.pool_scenarios import MARKER, apply_pool_scenarios, prepare_pool_scenarios
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog, install_organization_catalog, install_schema_catalog
from app.infrastructure.postgresql.seed_plan import source_fingerprint
from app.infrastructure.postgresql.seed_projects import seed_sample_projects


def install(connection, *, projects=True):
    ensure_reference_catalog(connection)
    install_schema_catalog(connection)
    install_organization_catalog(connection)
    if projects:
        seed_sample_projects(connection)


def sequences(connection):
    return connection.execute("SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='eppm' ORDER BY sequencename").fetchall()


def test_native_scenario_preview_does_not_mutate_rows_sequences_or_frozen_inputs_and_apply_is_additive(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    before = operator.run(lambda c: (source_fingerprint(c), sequences(c), c.execute('SELECT * FROM eppm.project_task ORDER BY id').fetchall()))
    plan = operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=20260908))
    assert operator.run(lambda c: (source_fingerprint(c), sequences(c), c.execute('SELECT * FROM eppm.project_task ORDER BY id').fetchall())) == before
    assert plan.report() == operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=20260908)).report()
    preview = plan.report()
    assert (preview['new_groups'], preview['new_pools'], preview['new_employee_mappings']) == (25, 100, 300)
    assert (preview['new_project_assignments'], preview['new_task_assignments']) == (100, 100)
    assert len(preview['parents']) == 5
    assert [row['normal_assigned_fte'] for row in preview['scenarios'][:4]] == [0, 4, 4, 4]
    assert [row['theoretical_fte'] for row in preview['scenarios'][:4]] == [3, 2, 6, 4]
    preview['scenarios'][0]['pool_id'] = -1
    assert plan.report()['scenarios'][0]['pool_id'] > 0
    with pytest.raises(FrozenInstanceError):
        plan.inserts[0].values = ()
    report = operator.run(lambda c: apply_pool_scenarios(c, plan), write=True)
    assert report['applied']
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_group').fetchone() == (31,)
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool').fetchone() == (103,)
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_mapping').fetchone() == (307,)
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_assignment').fetchone() == (200,)
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_group_member').fetchone() == (130,)
        assert connection.execute('SELECT * FROM eppm.project_task ORDER BY id').fetchall() == before[2]
        for row in report['scenarios']:
            assert connection.execute('SELECT capacity_fte FROM eppm.resource_pool WHERE id=%s', (row['pool_id'],)).fetchone() == (row['theoretical_fte'],)
        assert connection.execute("INSERT INTO eppm.resource_pool(name) VALUES ('Later') RETURNING id").fetchone()[0] > 103
    repeat = operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=20260908))
    assert repeat.inserts == ()
    assert operator.run(lambda c: apply_pool_scenarios(c, repeat), write=True) == {
        'applied': False, 'already_seeded': True, 'new_groups': 0, 'new_pools': 0,
    }


@pytest.mark.parametrize('projects', [False, True])
def test_scenarios_support_empty_projects_and_project_only_native_year_dates(pg_database, projects):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(lambda c: install(c, projects=projects), write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute('DELETE FROM eppm.task_dependencies')
        connection.execute('DELETE FROM eppm.project_task')
        connection.execute("INSERT INTO eppm.resource_pool_group(id,name) VALUES (999,' Service custom '),(1000,'Service ignored / nested')")
    plan = operator.run(lambda c: prepare_pool_scenarios(c, year=2028, seed=7))
    assert plan.report()['new_pools'] == 20
    assert plan.report()['new_project_assignments'] == (20 if projects else 0)
    assert plan.report()['new_task_assignments'] == 0
    operator.run(lambda c: apply_pool_scenarios(c, plan), write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        periods = connection.execute('SELECT DISTINCT start_date,end_date FROM eppm.resource_pool_assignment').fetchall()
        assert periods == ([(date(2028, 1, 1), date(2028, 12, 31))] if projects else [])
        assert connection.execute('SELECT min(id) FROM eppm.resource_pool_group WHERE description=%s', (MARKER,)).fetchone()[0] > 1000


@pytest.mark.parametrize('change', [
    "UPDATE eppm.employee SET occupation_percentage=50 WHERE employee_id=1",
    "UPDATE eppm.project SET name='Changed' WHERE id=1",
    "UPDATE eppm.resource_pool SET name='Changed' WHERE id=1",
    "INSERT INTO eppm.operator_seed_state(catalog) VALUES ('demo')",
])
def test_scenario_apply_rejects_changed_business_sources_without_partial_inserts(pg_database, change):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    plan = operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=1))
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute(change)
    with pytest.raises(ValueError, match='changed during preparation'):
        operator.run(lambda c: apply_pool_scenarios(c, plan), write=True)
    assert operator.run(lambda c: c.execute('SELECT count(*) FROM eppm.resource_pool_group').fetchone()) == (0,)


@pytest.mark.parametrize('year,seed', [(0, 1), (10000, 1), (True, 1), (2026, False)])
def test_invalid_scenario_options_are_rejected_without_writes(pg_database, year, seed):
    with pytest.raises(ValueError, match='integer'):
        OperatorDatabase(pg_database.operator_url).run(lambda c: prepare_pool_scenarios(c, year=year, seed=seed))


@pytest.mark.parametrize('setup,message', [
    ("UPDATE eppm.employee SET occupation_percentage=0", 'three employed'),
    ("INSERT INTO eppm.resource_pool_group(name,description) VALUES ('Legacy','Pool hierarchy capacity scenarios v1')", 'Legacy'),
    ("INSERT INTO eppm.resource_pool_group(name) VALUES ('Service A'),('Service A / Unit 01')", 'name already exists'),
])
def test_invalid_scenario_sources_fail_during_read_only_preview(pg_database, setup, message):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute(setup)
    before = operator.run(lambda c: (source_fingerprint(c), sequences(c)))
    with pytest.raises(ValueError, match=message):
        operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=1))
    assert operator.run(lambda c: (source_fingerprint(c), sequences(c))) == before


def test_rolled_back_sequence_advances_do_not_invalidate_a_frozen_replayable_plan(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    plan = operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=1))
    attempts = []

    def apply(connection):
        attempts.append(1)
        report = apply_pool_scenarios(connection, plan)
        if len(attempts) == 1:
            connection.execute("DO $$ BEGIN RAISE EXCEPTION 'retry' USING ERRCODE='40001'; END $$")
        return report

    assert operator.run(apply, write=True)['applied']
    assert len(attempts) == 2
    assert operator.run(lambda c: c.execute('SELECT count(*) FROM eppm.resource_pool_group').fetchone()) == (31,)


@pytest.mark.parametrize('table', ['catalog_cache_revision', 'project_cache_revision', 'pool_cache_revision'])
def test_missing_source_metadata_fails_closed(pg_database, table):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute(f'DELETE FROM eppm.{table}')
    with pytest.raises(ValueError, match='metadata is unavailable'):
        operator.run(source_fingerprint)


def test_native_scenario_categories_match_actual_staffing_and_preserve_project_records(pg_database):
    """Check every generated category against persisted employee and allocation data."""
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    tables = ('project', 'project_task', 'task_dependencies', 'project_property_value', 'project_property_value_item')
    with psycopg.connect(pg_database.operator_url) as connection:
        before = {table: connection.execute(f'SELECT * FROM eppm.{table} ORDER BY 1,2').fetchall() for table in tables}
    plan = operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=20260908))
    assert operator.run(lambda c: apply_pool_scenarios(c, plan), write=True)['applied']
    with psycopg.connect(pg_database.operator_url) as connection:
        assert {table: connection.execute(f'SELECT * FROM eppm.{table} ORDER BY 1,2').fetchall() for table in tables} == before
        rows = connection.execute('''SELECT g.id,p.id,p.name,p.capacity_fte,
            coalesce(sum(e.occupation_percentage*m.allocation_pct/10000),0),count(e.employee_id)
            FROM eppm.resource_pool_group g JOIN eppm.resource_pool_group_member gm ON gm.group_id=g.id
            JOIN eppm.resource_pool p ON p.id=gm.pool_id
            LEFT JOIN eppm.resource_pool_mapping m ON m.pool_id=p.id AND m.target_type='employee'
            LEFT JOIN eppm.employee e ON e.employee_id=m.target_id
            WHERE g.description=%s GROUP BY g.id,p.id ORDER BY g.id,p.id''', (MARKER,)).fetchall()
        groups = Counter(row[0] for row in rows)
        assert len(groups) == 25 and set(groups.values()) == {4}
        for _, _, name, theoretical, nominal, employees in rows:
            if name.endswith('/ Unallocated'):
                assert employees == 0 and theoretical > 0
            elif name.endswith('/ Overassigned'):
                assert nominal > theoretical
            elif name.endswith('/ Underassigned'):
                assert 0 < nominal < theoretical
            else:
                assert name.endswith('/ Fully assigned') and nominal == theoretical
        assignments = connection.execute('''SELECT pool_id,count(*) FROM eppm.resource_pool_assignment
            WHERE pool_id=ANY(%s::bigint[]) GROUP BY pool_id ORDER BY pool_id''', ([row[1] for row in rows],)).fetchall()
        assert assignments == [(pool_id, 2) for pool_id in sorted(row[1] for row in rows)]
        services = connection.execute('''SELECT g.id,count(m.child_group_id) FROM eppm.resource_pool_group g
            JOIN eppm.resource_pool_group_member m ON m.group_id=g.id
            WHERE g.name LIKE 'Service %%' AND g.description<>%s GROUP BY g.id''', (MARKER,)).fetchall()
        assert len(services) == 5 and {count for _, count in services} == {5}
