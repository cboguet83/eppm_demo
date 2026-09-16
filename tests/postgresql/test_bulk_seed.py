"""Native generator constraints, template parity, append behavior and exact budgets."""

from tests.postgresql.plan_fixtures import seed_test_plans
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from app.application.ports.maintenance import SeedRequest
from app.infrastructure.postgresql import maintenance
from app.infrastructure.postgresql.backup import PostgresBackup, restore_database
from app.infrastructure.postgresql.bulk_seed import generate_projects
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.infrastructure.postgresql.seed_plan import source_fingerprint


@pytest.mark.parametrize('minimum,maximum', [(0, 0), (0, 1), (1, 1), (3, 8), (0, 15), (12, 50), (50, 50)])
def test_bulk_generator_preserves_requested_schedule_bounds_native_links_tags_and_decimal_budgets(pg_database, minimum, maximum):
    operator = OperatorDatabase(pg_database.operator_url)
    request = SeedRequest(projects=15, min_tasks=minimum, max_tasks=maximum, random_seed=123)
    result = operator.run(lambda c: generate_projects(c, request, year=2026), write=True)
    assert result['projects_created'] == 15
    assert result['pools_created'] == 40 and result['container_pools_created'] == 7
    assert 15 * minimum <= result['tasks_created'] <= 15 * maximum
    with psycopg.connect(pg_database.operator_url) as connection:
        counts = connection.execute('SELECT p.id,count(t.id) FROM eppm.project p LEFT JOIN eppm.project_task t ON t.project_id=p.id GROUP BY p.id').fetchall()
        assert all(minimum <= count <= maximum for _, count in counts)
        assert connection.execute('SELECT count(*) FROM eppm.project_tag').fetchone() == (15,)
        assert connection.execute('SELECT count(*) FROM eppm.task_tag').fetchone() == (result['tasks_created'],)
        allocated, used_pools = connection.execute('SELECT count(DISTINCT project_id),count(DISTINCT pool_id) FROM eppm.resource_pool_assignment').fetchone()
        assert allocated <= sum(count > 0 for _, count in counts)
        assert 0 <= used_pools <= 33
        assert (allocated > 0) == (result['tasks_created'] > 0)
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_assignment WHERE start_date IS NOT NULL OR end_date IS NOT NULL OR fte_assigned<.1 OR fte_assigned>5').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.project_property_value').fetchone() == (result['property_values_created'],)
        for planned, actual in connection.execute('SELECT planned_budget,actual_budget FROM eppm.project'):
            assert isinstance(planned, Decimal) and isinstance(actual, Decimal)
            assert Decimal(50_000) <= planned <= Decimal(3_000_000)
            assert 0 <= actual <= planned
            assert planned == planned.quantize(Decimal('0.01'))
        assert connection.execute('SELECT count(*) FROM eppm.project_task WHERE end_date<start_date').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.task_dependencies d JOIN eppm.project_task t ON t.id=d.task_id '
                                  'JOIN eppm.project_task p ON p.id=d.predecessor_task_id '
                                  'WHERE d.predecessor_project_id IS NOT NULL AND d.predecessor_project_id<>p.project_id').fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM eppm.project p JOIN eppm.project_task t ON p.id=t.project_id "
                                  "WHERE (p.status='Completed' AND t.progress_pct<>100) OR (p.status='Draft' AND t.progress_pct<>0)").fetchone() == (0,)


def test_bulk_append_preserves_custom_templates_existing_records_and_sequence_gaps(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(ensure_reference_catalog, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name) VALUES ('Custom')")
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type,mandatory) VALUES ('CHOICE','Choice','ENUM',true)")
        connection.execute("INSERT INTO eppm.schema_param_options(param_id,option_value) VALUES ('CHOICE','Configured')")
        connection.execute("INSERT INTO eppm.project(id,name) VALUES (999,'Existing')")
        seed_test_plans(connection)
        from app.infrastructure.postgresql.seed_plan import ensure_operator_plan
        ensure_operator_plan(connection, 999)
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (9999,999,'Keep','2026-01-01','2026-01-02',(SELECT id FROM eppm.project_plan WHERE project_id=999 AND is_current))")
        connection.execute("SELECT setval('eppm.project_id_seq',1099,true),setval('eppm.project_task_id_seq',10999,true)")
    result = operator.run(lambda c: generate_projects(c, SeedRequest(projects=4, min_tasks=1, max_tasks=1, clean_first=False), year=2026), write=True)
    assert result == {'projects_created': 4, 'tasks_created': 4, 'dependencies_created': 1,
                      'project_types': 2, 'property_values_created': 4, 'pools_created': 0, 'container_pools_created': 0}
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT id FROM eppm.project ORDER BY id').fetchall() == [(999,), (1100,), (1101,), (1102,), (1103,)]
        assert connection.execute('SELECT id FROM eppm.project_task ORDER BY id').fetchall() == [(9999,), (11000,), (11001,), (11002,), (11003,)]
        assert connection.execute('SELECT task_name,start_date,end_date FROM eppm.project_task WHERE id=9999').fetchone() == ('Keep', date(2026, 1, 1), date(2026, 1, 2))
        assert connection.execute('SELECT DISTINCT text_value FROM eppm.project_property_value').fetchall() == [('Configured',)]
        assert connection.execute('SELECT count(*) FROM eppm.employee').fetchone() == (0,)


def test_invalid_required_custom_template_rolls_back_bulk_write_and_keeps_existing_rows(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(ensure_reference_catalog, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type,mandatory) VALUES ('EMPTY','Empty','ENUM',true)")
        connection.execute("INSERT INTO eppm.project(name) VALUES ('Existing')")
        seed_test_plans(connection)
    before = operator.run(source_fingerprint)
    with pytest.raises(ValueError, match='no configured options'):
        operator.run(lambda c: generate_projects(c, SeedRequest(projects=3, clean_first=False), year=2026), write=True)
    assert operator.run(source_fingerprint) == before


def test_bulk_command_creates_one_pre_reset_archive_and_cli_append_retains_generated_projects(pg_database, restore_target, clients, tmp_path, monkeypatch):
    from scripts.postgresql_admin import main

    operator = OperatorDatabase(pg_database.operator_url)
    backup = PostgresBackup(pg_database.operator_url, tmp_path, tools=clients)
    maintenance.seed_defaults(operator, backup, year=2026)
    before = set(tmp_path.glob('*.dump'))
    result = maintenance.seed_projects(operator, backup, SeedRequest(projects=4, max_tasks=0))
    assert result['projects_created'] == 4 and result['tasks_created'] == 0
    archives = set(tmp_path.glob('*.dump')) - before
    assert len(archives) == 1
    restore_database(archives.pop(), restore_target.operator_url, tools=clients)
    assert maintenance.counts(OperatorDatabase(restore_target.operator_url))['projects'] == 5
    monkeypatch.setenv('EPPM_TEST_BULK_URL', pg_database.operator_url)
    monkeypatch.setattr('sys.argv', ['postgresql_admin', '--url-variable', 'EPPM_TEST_BULK_URL', '--backup-directory', str(tmp_path),
                                  'seed-projects', '--projects', '2', '--min-tasks', '2', '--max-tasks', '3', '--seed', '7', '--append'])
    main(archive_tools=clients)
    assert maintenance.counts(operator)['projects'] == 6
    assert len(set(tmp_path.glob('*.dump')) - before) == 2


@pytest.mark.parametrize('seed_request', [
    SeedRequest(projects=-1), SeedRequest(projects=True), SeedRequest(min_tasks=-1),
    SeedRequest(min_tasks=5, max_tasks=4), SeedRequest(max_tasks=51),
    SeedRequest(random_seed=True), SeedRequest(clean_first=1),
])
def test_invalid_bulk_options_fail_before_creating_an_archive(pg_database, tmp_path, seed_request):
    with pytest.raises(ValueError, match='Invalid'):
        maintenance.seed_projects(OperatorDatabase(pg_database.operator_url), PostgresBackup(pg_database.operator_url, tmp_path), seed_request)
    assert list(tmp_path.iterdir()) == []


def test_unfrozen_randomness_is_rejected_at_the_transaction_helper_boundary(pg_database):
    with pytest.raises(ValueError, match='Freeze'):
        OperatorDatabase(pg_database.operator_url).run(lambda c: generate_projects(c, SeedRequest(random_seed=None), year=2026), write=True)


def test_operator_bulk_seed_refreshes_planner_statistics_before_initial_and_append_reads(pg_database, tmp_path, clients):
    """Do not rely on a later autovacuum to make the newly seeded workload usable."""
    tables = ('project', 'project_task', 'task_dependencies', 'project_property_value', 'resource_pool_assignment')
    with psycopg.connect(pg_database.operator_url) as connection:
        for name in tables:
            connection.execute(psycopg.sql.SQL('ALTER TABLE eppm.{} SET (autovacuum_enabled=false)').format(psycopg.sql.Identifier(name)))
    operator = OperatorDatabase(pg_database.operator_url)
    backup = PostgresBackup(pg_database.operator_url, tmp_path, tools=clients)
    for count in (30, 10):
        maintenance.seed_projects(operator, backup, SeedRequest(projects=count, min_tasks=1, max_tasks=3, random_seed=42))
        with psycopg.connect(pg_database.operator_url) as connection:
            for name in tables:
                actual = connection.execute(psycopg.sql.SQL('SELECT count(*) FROM eppm.{}').format(psycopg.sql.Identifier(name))).fetchone()[0]
                estimated = connection.execute('SELECT reltuples FROM pg_catalog.pg_class WHERE oid=%s::regclass', ('eppm.' + name,)).fetchone()[0]
                assert actual > 0 and estimated == actual, name


def test_empty_workload_and_optional_empty_categories_preserve_valid_custom_catalogs(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(ensure_reference_catalog, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES ('OPTIONAL','Optional','ENUM')")
    result = operator.run(lambda c: generate_projects(c, SeedRequest(projects=0, clean_first=False), year=2026), write=True)
    assert result['projects_created'] == result['tasks_created'] == result['property_values_created'] == result['pools_created'] == 0
    result = operator.run(lambda c: generate_projects(c, SeedRequest(projects=2, clean_first=False), year=2026), write=True)
    assert result['projects_created'] == 2 and result['property_values_created'] == 0


def test_missing_all_project_types_is_a_safe_validation_error(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.operator_seed_state(catalog) VALUES ('reference'),('demo')")
    with pytest.raises(ValueError, match='Create a project type'):
        operator.run(lambda c: generate_projects(c, SeedRequest(projects=1, clean_first=False), year=2026), write=True)


def test_none_random_seed_is_frozen_once_across_a_real_database_retry(pg_database, clients, tmp_path, monkeypatch):
    operator = OperatorDatabase(pg_database.operator_url)
    backup = PostgresBackup(pg_database.operator_url, tmp_path, tools=clients)
    attempts = []
    entropy = []
    monkeypatch.setattr(maintenance, 'randbits', lambda bits: entropy.append(bits) or 123)

    def run(connection, seed_request, *, year, today):
        attempts.append((seed_request.random_seed, today))
        result = generate_projects(connection, seed_request, year=year, today=today)
        if len(attempts) == 1:
            connection.execute("DO $$ BEGIN RAISE EXCEPTION 'retry' USING ERRCODE='40001'; END $$")
        return result

    monkeypatch.setattr(maintenance, 'generate_projects', run)
    result = maintenance.seed_projects(operator, backup, SeedRequest(projects=3, random_seed=None))
    assert result['projects_created'] == 3
    assert attempts[0] == attempts[1] and attempts[0][0] == 123 and entropy == [128]
    assert len(list(tmp_path.glob('*.dump'))) == 1
    assert maintenance.counts(operator)['projects'] == 3


def test_thousand_project_status_mix_and_completed_dates(pg_database):
    """Native rows meet exact large-portfolio quotas and the injected date cutoff."""
    cutoff = date(2026, 9, 14)
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(lambda connection: generate_projects(connection,
        SeedRequest(projects=1000, min_tasks=1, max_tasks=3), year=2026, today=cutoff), write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert dict(connection.execute('SELECT status,count(*) FROM eppm.project GROUP BY status')) == {
            'In Progress': 780, 'Completed': 100, 'Cancelled': 50, 'Draft': 40, 'On Hold': 30}
        assert connection.execute("SELECT count(*) FROM eppm.project p JOIN eppm.project_task t ON t.project_id=p.id WHERE p.status='Completed' AND (t.end_date >= %s OR t.progress_pct<>100)", (cutoff,)).fetchone() == (0,)


def test_concurrent_task_insert_between_reservation_and_copy_keeps_distinct_native_ids(pg_database, monkeypatch):
    from app.infrastructure.postgresql import bulk_seed

    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(ensure_reference_catalog, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        project = connection.execute("INSERT INTO eppm.project(name) VALUES ('Existing') RETURNING id").fetchone()[0]
        seed_test_plans(connection)
        from app.infrastructure.postgresql.seed_plan import ensure_operator_plan
        ensure_operator_plan(connection, project)
    original = bulk_seed._identities
    external = []

    def reserve(connection, table, count):
        identities = original(connection, table, count)
        if table == 'project_task':
            with psycopg.connect(pg_database.operator_url) as other:
                external.append(other.execute("INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date,project_plan_id) "
                    "VALUES (%s,'Concurrent','2026-01-01','2026-01-02',(SELECT id FROM eppm.project_plan WHERE project_id=%s AND is_current)) RETURNING id", (project, project)).fetchone()[0])
        return identities

    monkeypatch.setattr(bulk_seed, '_identities', reserve)
    result = operator.run(lambda c: generate_projects(c, SeedRequest(projects=3, min_tasks=1, max_tasks=1, clean_first=False), year=2026), write=True)
    assert result['tasks_created'] == 3 and len(external) == 1
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.project_task').fetchone() == (4,)
        assert connection.execute('SELECT task_name FROM eppm.project_task WHERE id=%s', (external[0],)).fetchone() == ('Concurrent',)
