"""Revision reads retain bounded query work after repeated pooled execution."""

from tests.postgresql.plan_fixtures import seed_test_plans
import psycopg
import pytest

from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.migration import check_schema, discover_migrations, migrate


@pytest.fixture
def revision_workload(authorized):
    """Seed a large synthetic graph in this test's separately owned database."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name) SELECT id,'Project '||id FROM generate_series(4,10001) id")
        seed_test_plans(connection)
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) SELECT id,'Pool '||id,10 FROM generate_series(1,100) id")
        connection.execute("""INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id)
            SELECT (project.id-1)*7+n,project.id,'Task '||n,'2026-01-01'::date+n,'2026-01-01'::date+n+1,(SELECT id FROM eppm.project_plan WHERE project_id=project.id AND is_current)
            FROM eppm.project project CROSS JOIN generate_series(1,7) n""")
        connection.execute("""INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id)
            SELECT id,id-1 FROM eppm.project_task WHERE id>1""")
        connection.execute("""INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned,project_plan_id)
            SELECT 1+(id%100),id,(id-1)*7+1,0.5,(SELECT id FROM eppm.project_plan WHERE project_id=project.id AND is_current) FROM eppm.project""")
        for table in ('project', 'project_task', 'task_dependencies', 'resource_pool',
                      'resource_pool_assignment', 'project_cache_revision', 'pool_cache_revision'):
            connection.execute('ANALYZE eppm.' + table)
    return authorized


def test_repeated_full_scope_revisions_do_not_multiply_database_work(revision_workload, record_property):
    def inspect(connection: psycopg.Connection) -> dict:
        connection.execute("SET LOCAL plan_cache_mode = 'auto'")
        query = 'SELECT eppm.display_cache_revisions()'
        expected = connection.execute(query).fetchone()[0]
        before = connection.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + query).fetchone()[0][0]
        for _ in range(8):
            assert connection.execute(query).fetchone()[0] == expected
        after = connection.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + query).fetchone()[0][0]
        assert connection.execute('SHOW plan_cache_mode').fetchone()[0] == 'auto'
        assert [row[0] for row in expected['projects']] == list(range(1, 10002))
        assert expected['projects'][0][3] == []
        assert expected['projects'][1][3] == [1]
        assert expected['pools'][0][4] == list(range(100, 10001, 100))
        return {'before': before, 'after': after}

    fixture = revision_workload
    plans = run_business(fixture.database, fixture.key, fixture.binding(4).access, inspect)
    blocks = {name: plan['Plan']['Shared Hit Blocks'] + plan['Plan']['Shared Read Blocks']
              for name, plan in plans.items()}
    for name, plan in plans.items():
        record_property(name + '_revision_ms', plan['Execution Time'])
        record_property(name + '_revision_blocks', blocks[name])
    # Compare actual database work, not a host-dependent wall-clock threshold or
    # a literal planner setting. Repeated reads of the same graph must not jump
    # to a plan that probes the same indexes hundreds of thousands of times.
    assert blocks['after'] <= blocks['before'] * 2 + 256, blocks


def test_revision_plan_upgrade_preserves_existing_schema_history_and_function_security(empty_database, tmp_path):
    migrations = discover_migrations()
    for migration in migrations[:22]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    metadata = ("SELECT prosrc,proowner,prosecdef,provolatile,proacl::text FROM pg_proc "
                "WHERE oid='eppm.display_cache_revisions()'::regprocedure")
    ledger = 'SELECT version,name,checksum FROM eppm.schema_migration ORDER BY version'
    with psycopg.connect(empty_database.operator_url) as connection:
        before_function = connection.execute(metadata).fetchone()
        before_ledger = connection.execute(ledger).fetchall()

    assert migrate(empty_database.operator_url) == tuple(item.name for item in migrations[22:])

    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute(metadata).fetchone() == before_function
        assert connection.execute(ledger).fetchall()[:22] == before_ledger
    with psycopg.connect(empty_database.runtime_url) as connection:
        check_schema(connection)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute('ALTER FUNCTION eppm.display_cache_revisions() RESET plan_cache_mode')
