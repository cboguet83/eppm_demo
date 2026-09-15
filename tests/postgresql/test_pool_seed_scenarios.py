"""Real PostgreSQL replacement safety, exact hierarchy and calculated demand."""

from collections import Counter
from dataclasses import FrozenInstanceError, replace
from datetime import date

import psycopg
import pytest

from app.application.ports.maintenance import SeedRequest
from app.domain.resources.capacity import calculate_capacity
from app.domain.resources.pool_seed import GROUPS, POOLS
from app.infrastructure.postgresql.bulk_seed import generate_projects
from app.infrastructure.postgresql.operator_capacity import read_operator_capacity_inputs
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.infrastructure.postgresql.pool_scenarios import apply_pool_scenarios, prepare_pool_scenarios
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog, install_organization_catalog, install_schema_catalog
from app.infrastructure.postgresql.seed_plan import SeedInsert, source_fingerprint
from app.infrastructure.postgresql.seed_projects import seed_sample_projects


def install(connection, *, projects=True):
    ensure_reference_catalog(connection)
    install_schema_catalog(connection)
    install_organization_catalog(connection)
    if projects:
        seed_sample_projects(connection)


def snapshot(connection):
    return (source_fingerprint(connection), connection.execute(
        "SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='eppm' ORDER BY sequencename").fetchall())


def test_preview_is_non_mutating_frozen_and_repeat_install_preserves_allocations(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    before = operator.run(snapshot)
    plan = operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=42))
    assert operator.run(snapshot) == before
    assert plan == operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=42))
    report = plan.report()
    assert (report['new_containers'], report['new_pools'], report['new_employee_mappings']) == (7, 40, 0)
    report['hierarchy'][0]['name'] = 'Mutated'
    assert plan.report()['hierarchy'][0]['name'] == 'Ressort A'
    with pytest.raises(FrozenInstanceError):
        plan.inserts = ()
    operator.run(lambda c: apply_pool_scenarios(c, plan), write=True)
    before = operator.run(snapshot)
    repeat = operator.run(lambda c: prepare_pool_scenarios(c, year=2027, seed=999))
    assert not repeat.inserts
    assert not operator.run(lambda c: apply_pool_scenarios(c, repeat), write=True)['applied']
    assert operator.run(snapshot) == before


def test_capacity_exceptions_are_applied_after_unchanged_assignment_plan(pg_database):
    """Post-assignment reductions change capacity, never the seeded demand."""
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    plan = operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=42))
    exceptions = [i for i, command in enumerate(plan.inserts) if command.table == 'resource_pool_capacity_exception']
    assignments = [i for i, command in enumerate(plan.inserts) if command.table == 'resource_pool_assignment']
    assert min(exceptions) > max(assignments)
    before_reductions = replace(plan, inserts=plan.inserts[:min(exceptions)])
    operator.run(lambda c: apply_pool_scenarios(c, before_reductions), write=True)
    before = operator.run(lambda c: c.execute('SELECT * FROM eppm.resource_pool_assignment ORDER BY id').fetchall())
    def add_reductions(c):
        for command in plan.inserts[min(exceptions):]:
            command.apply(c)
    operator.run(add_reductions, write=True)
    assert operator.run(lambda c: c.execute('SELECT * FROM eppm.resource_pool_assignment ORDER BY id').fetchall()) == before
    def check(c):
        rows = c.execute('''SELECT p.name,p.capacity_fte,x.start_date,x.end_date,x.reduction_fte
            FROM eppm.resource_pool p JOIN eppm.resource_pool_capacity_exception x ON x.pool_id=p.id''').fetchall()
        counts = Counter()
        for name, capacity, start, end, reduction in rows:
            months = (end.year-start.year)*12+end.month-start.month+1
            counts[name, months] += 1
            assert reduction == 1
            assert capacity > 6 or months == 6
        for pool in POOLS:
            assert 1 <= counts[pool.name, 6] <= 3
            assert counts[pool.name, 12] == (2 if pool.capacity > 6 else 0)
        identities = [row[0] for row in c.execute('SELECT p.id FROM eppm.resource_pool p WHERE NOT EXISTS (SELECT 1 FROM eppm.resource_pool child WHERE child.parent_pool_id=p.id)')]
        for inputs in read_operator_capacity_inputs(c, identities).values():
            detail = calculate_capacity(inputs, today=date(2026, 1, 1))
            assert detail.capacity_calendar
            assert all(value < inputs.pool.capacity_fte for value in detail.capacity_calendar.values())
    operator.run(check)


def test_current_size_replacement_preserves_projects_and_has_exact_capacity_mix(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(lambda c: generate_projects(c, SeedRequest(projects=1000, min_tasks=0, max_tasks=3), year=2026), write=True)
    tables = ('project', 'project_task', 'task_dependencies', 'employee', 'team', 'project_property_value', 'project_property_value_item')
    def preserved(c):
        return {table: c.execute(f'SELECT * FROM eppm.{table} ORDER BY 1,2').fetchall() for table in tables}
    before = operator.run(preserved)
    old_max = operator.run(lambda c: c.execute('SELECT max(id) FROM eppm.resource_pool').fetchone()[0])
    plan = operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=42, replace=True))
    assert plan.report()['allocated_projects'] + plan.report()['unallocated_projects'] == 1000
    assert plan.report()['unallocated_projects'] > 0
    operator.run(lambda c: apply_pool_scenarios(c, plan), write=True)
    assert operator.run(preserved) == before
    with psycopg.connect(pg_database.operator_url) as c:
        assert c.execute('SELECT count(DISTINCT project_id),count(DISTINCT pool_id) FROM eppm.resource_pool_assignment').fetchone() == (plan.report()['allocated_projects'], 33)
        assert c.execute('SELECT count(*) FROM eppm.resource_pool_mapping').fetchone() == (0,)
        assert c.execute('SELECT count(*) FROM eppm.resource_pool_assignment WHERE task_id IS NOT NULL').fetchone()[0] > 0
        assert c.execute('SELECT count(*) FROM eppm.resource_pool_assignment WHERE start_date IS NOT NULL OR end_date IS NOT NULL OR fte_assigned<.1 OR fte_assigned>5').fetchone() == (0,)
        assert c.execute('WITH ordered AS (SELECT id,row_number() OVER(ORDER BY id) AS n FROM eppm.project) SELECT count(*) FROM eppm.resource_pool_assignment a JOIN ordered p ON p.id=a.project_id WHERE (p.n<=250 AND a.task_id IS NOT NULL) OR (p.n>250 AND a.task_id IS NULL)').fetchone() == (0,)
        rows = c.execute('SELECT p.name,g.name,h.code,p.capacity_fte FROM eppm.resource_pool p '
                         'JOIN eppm.resource_pool g ON g.id=p.parent_pool_id '
                         'JOIN eppm.hierarchy_type h ON h.id=p.hierarchy_type_id WHERE p.capacity_fte IS NOT NULL').fetchall()
        assert set(rows) == {(p.name, p.parent, p.hierarchy_type, p.capacity) for p in POOLS}
        groups = c.execute('SELECT g.name,parent.name,h.code FROM eppm.resource_pool g '
                           'LEFT JOIN eppm.resource_pool parent ON parent.id=g.parent_pool_id '
                           'JOIN eppm.hierarchy_type h ON h.id=g.hierarchy_type_id WHERE g.capacity_fte IS NULL').fetchall()
        assert set(groups) == set(GROUPS)
        ids = [r[0] for r in c.execute('SELECT p.id FROM eppm.resource_pool p WHERE NOT EXISTS (SELECT 1 FROM eppm.resource_pool child WHERE child.parent_pool_id=p.id)')]
        assert min(ids) > old_max
        categories = Counter()
        for values in read_operator_capacity_inputs(c, ids).values():
            detail = calculate_capacity(values, today=date(2026, 1, 1))
            assert detail.effective_capacity_fte == values.pool.capacity_fte
            usage = [value / detail.effective_capacity_fte for value in detail.daily_usage.values() if value > 0]
            assert max(usage, default=0) <= 1.800001
            if values.pool.name in ('pool E1', 'pool E2'):
                assert max(usage, default=0) <= .800001
            if max(usage, default=0) > 1.001:
                assert max(usage) <= 1.800001
                categories['over'] += 1
            elif min(usage, default=0) < .999:
                assert min(usage, default=0) < 1
                categories['under'] += 1
            else:
                categories['full'] += 1
        assert categories['over'] <= plan.report()['overallocated_pools'] == 7
        assert categories['under'] >= 4
    assignments = operator.run(lambda c: c.execute('SELECT * FROM eppm.resource_pool_assignment ORDER BY id').fetchall())
    operator.run(lambda c: generate_projects(c, SeedRequest(projects=5, clean_first=False), year=2026), write=True)
    assert operator.run(lambda c: c.execute('SELECT * FROM eppm.resource_pool_assignment ORDER BY id').fetchall()) == assignments


def test_replace_opt_in_and_missing_reference_codes_preserve_existing_labels(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    with psycopg.connect(pg_database.operator_url) as c:
        c.execute("INSERT INTO eppm.resource_pool(name) VALUES ('Old')")
        c.execute("DELETE FROM eppm.hierarchy_type WHERE code='division'")
        c.execute("UPDATE eppm.hierarchy_type_translation SET label='My Ressort' WHERE hierarchy_type_id=(SELECT id FROM eppm.hierarchy_type WHERE code='ressort') AND locale='en'")
    with pytest.raises(ValueError, match='--replace'):
        operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=1))
    before = operator.run(snapshot)
    plan = operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=1, replace=True))
    assert operator.run(snapshot) == before
    operator.run(lambda c: apply_pool_scenarios(c, plan), write=True)
    assert operator.run(lambda c: c.execute("SELECT label FROM eppm.hierarchy_type_translation t JOIN eppm.hierarchy_type h ON h.id=t.hierarchy_type_id WHERE h.code='ressort' AND locale='en'").fetchone()) == ('My Ressort',)


@pytest.mark.parametrize('change', ["UPDATE eppm.project SET name='Changed' WHERE id=1", "UPDATE eppm.employee SET occupation_percentage=50 WHERE employee_id=1", "INSERT INTO eppm.resource_pool(name) VALUES ('Changed')"])
def test_stale_sources_rejected_without_replacement(pg_database, change):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    plan = operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=1, replace=True))
    operator.run(lambda c: c.execute(change), write=True)
    before = operator.run(snapshot)
    with pytest.raises(ValueError, match='changed during preparation'):
        operator.run(lambda c: apply_pool_scenarios(c, plan), write=True)
    assert operator.run(snapshot) == before


def test_failure_after_delete_rolls_back_and_serialization_retry_replays(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    operator.run(lambda c: c.execute("INSERT INTO eppm.resource_pool(name) VALUES ('Retain on failure')"), write=True)
    plan = operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=1, replace=True))
    broken = replace(plan, inserts=(*plan.inserts, SeedInsert('resource_pool', ('name', 'capacity_fte'), ('Invalid', -1))))
    with pytest.raises(psycopg.errors.CheckViolation):
        operator.run(lambda c: apply_pool_scenarios(c, broken), write=True)
    assert operator.run(lambda c: c.execute('SELECT name FROM eppm.resource_pool').fetchall()) == [('Retain on failure',)]
    attempts = []
    def apply(c):
        attempts.append(1)
        result = apply_pool_scenarios(c, plan)
        if len(attempts) == 1:
            c.execute("DO $$ BEGIN RAISE EXCEPTION 'retry' USING ERRCODE='40001'; END $$")
        return result
    assert operator.run(apply, write=True)['applied']
    assert len(attempts) == 2


@pytest.mark.parametrize('year,seed', [(0, 1), (10000, 1), (True, 1), (2026, False)])
def test_invalid_options_rejected(pg_database, year, seed):
    with pytest.raises(ValueError, match='integer'):
        OperatorDatabase(pg_database.operator_url).run(lambda c: prepare_pool_scenarios(c, year=year, seed=seed))


def test_replacement_backup_failure_leaves_existing_pools_intact(pg_database, tmp_path, monkeypatch):
    from app.application.exceptions import DatabaseMaintenanceError
    from app.infrastructure.postgresql import maintenance
    from app.infrastructure.postgresql.backup import PostgresBackup
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    operator.run(lambda c: c.execute("INSERT INTO eppm.resource_pool(name) VALUES ('Keep')"), write=True)
    backup = PostgresBackup(pg_database.operator_url, tmp_path)
    def fail(reason):
        raise OSError('Simulated archive failure')
    monkeypatch.setattr(backup, 'create', fail)
    before = operator.run(snapshot)
    with pytest.raises(DatabaseMaintenanceError):
        maintenance.seed_pool_scenarios(operator, backup, year=2026, replace=True, apply=True)
    assert operator.run(snapshot) == before


def test_project_without_tasks_uses_seed_year_and_short_task_dates_remain_inclusive(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    def setup(c):
        install(c, projects=False)
        c.execute("INSERT INTO eppm.project(id,name) VALUES (1,'Undated'),(2,'One day'),(3,'Two days')")
        c.execute("INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date) VALUES (2,'One','2027-02-03','2027-02-03'),(3,'Two','2027-02-03','2027-02-04')")
    operator.run(setup, write=True)
    plan = operator.run(lambda c: prepare_pool_scenarios(c, year=2028, seed=1))
    operator.run(lambda c: apply_pool_scenarios(c, plan), write=True)
    assert operator.run(lambda c: c.execute('SELECT project_id,min(start_date),max(end_date) FROM eppm.resource_pool_assignment GROUP BY project_id ORDER BY project_id').fetchall()) == [
        (2, None, None),
        (3, None, None),
    ]


def test_catalog_then_append_leaves_all_projects_unallocated(pg_database):
    from app.infrastructure.postgresql.seeder import install_default_data
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(lambda c: install_default_data(c, force=False, include_projects=False, year=2026), write=True)
    before = operator.run(lambda c: c.execute('SELECT * FROM eppm.resource_pool ORDER BY id').fetchall())
    operator.run(lambda c: generate_projects(c, SeedRequest(projects=10, clean_first=False), year=2026), write=True)
    assert operator.run(lambda c: c.execute('SELECT * FROM eppm.resource_pool ORDER BY id').fetchall()) == before
    assert operator.run(lambda c: c.execute('SELECT count(*) FROM eppm.resource_pool_assignment').fetchone()) == (0,)
