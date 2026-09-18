"""Narrow date joins preserve dashboard results and the aggregate privacy boundary."""

from datetime import date

import psycopg
import pytest

from app.infrastructure.postgresql.dashboard import _resource_breakdown
from app.infrastructure.postgresql.migration import check_schema, discover_migrations, migrate
from app.infrastructure.postgresql.staffing_projection import refresh_staffing
from tests.postgresql.test_dashboard import reader
from tests.postgresql.test_pool_capacity import DAY, staffing


SIGNATURE = ('eppm.dashboard_resource_breakdown_with_capacity'
             '(jsonb,bigint[],date,text,bigint,text,text[],bigint[])')
MIGRATION = '0059_dashboard_narrow_date_join.sql'


def test_upgrade_preserves_function_identity_permissions_and_only_changes_join_boundary(empty_database, tmp_path):
    """Upgrade the previous release atomically and retain all function security settings."""
    migrations = discover_migrations()
    for migration in migrations[:58]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    query = '''SELECT oid,proowner,proacl,prosecdef,provolatile,proconfig,
                      pg_get_functiondef(oid)
               FROM pg_proc WHERE oid=%s::regprocedure'''
    with psycopg.connect(empty_database.operator_url) as connection:
        before = connection.execute(query, (SIGNATURE,)).fetchone()

    assert migrate(empty_database.operator_url) == tuple(item.name for item in migrations[58:])
    with psycopg.connect(empty_database.operator_url) as connection:
        check_schema(connection)
        after = connection.execute(query, (SIGNATURE,)).fetchone()
        assert after[:-1] == before[:-1]
        assert after[-1] == before[-1].replace('), days AS (', '), days AS MATERIALIZED (')
    assert migrate(empty_database.operator_url) == ()
    with psycopg.connect(empty_database.runtime_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute('''SELECT eppm.dashboard_resource_breakdown_with_capacity(
                '[]',ARRAY[1]::bigint[],%s,NULL,NULL,'allocation',NULL,NULL)''', (DAY,))


@pytest.mark.parametrize(('project_ids', 'quarter', 'pool_id', 'metric', 'statuses', 'pool_ids'), [
    ([1], None, None, 'overallocation', None, None),
    ([1, 2], None, None, 'allocation', ['In Progress', 'Completed'], None),
    ([1], None, None, 'allocation', ['In Progress'], [1]),
    ([1], None, 2, 'overallocation', None, [2]),
    ([1], '2026-Q1', 1, 'allocation', None, [1]),
    ([1], '2026-Q1', 1, 'overallocation', ['In Progress'], [1]),
    ([1], None, None, 'allocation', None, []),
    ([], None, None, 'overallocation', None, None),
])
def test_narrow_join_matches_previous_reader_with_calendars_filters_and_private_demand(
    staffing, project_ids, quarter, pool_id, metric, statuses, pool_ids,
):
    """Compare every returned field through real restricted reads before/after tuning."""
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status=CASE id WHEN 2 THEN 'Completed' ELSE 'In Progress' END")
        definition = connection.execute('SELECT pg_get_functiondef(%s::regprocedure)', (SIGNATURE,)).fetchone()[0]
        assert '), days AS MATERIALIZED (' in definition
        connection.execute(definition.replace('), days AS MATERIALIZED (', '), days AS ('))
    dashboard = reader(staffing, 1)

    def snapshot():
        return dashboard._run(lambda connection, ids, _security: _resource_breakdown(
            connection, ids, DAY, quarter, pool_id, metric, statuses, pool_ids), project_ids)

    before = snapshot()
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute(next(item.sql for item in discover_migrations() if item.name == MIGRATION))
    after = snapshot()
    assert after == before
    assert 3 not in after['consumers']  # Hidden competitors only contribute aggregate demand.


def test_optimized_reader_keeps_leap_day_exceptions_peak_ties_and_private_consumers(staffing):
    """Exercise the optimized entry point with concurrent pools and a one-day exception."""
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.resource_pool_assignment')
        connection.execute('DELETE FROM eppm.resource_pool_mapping')
        connection.execute('UPDATE eppm.resource_pool SET capacity_fte=5')
        connection.execute('''INSERT INTO eppm.resource_pool_assignment
            (pool_id,project_id,fte_assigned,start_date,end_date,project_plan_id)
            SELECT pool,project,fte,first,last,
                (SELECT id FROM eppm.project_plan WHERE project_id=project AND is_current)
            FROM (VALUES (1,1,4,'2023-12-01'::date,'2024-06-30'::date),
                         (2,1,3,'2024-02-29'::date,'2024-03-01'::date),
                         (1,3,2,'2024-02-29'::date,'2024-02-29'::date))
                 rows(pool,project,fte,first,last)''')
        connection.execute('''INSERT INTO eppm.resource_pool_capacity_exception
            (pool_id,start_date,end_date,reduction_fte) VALUES (1,'2024-02-29','2024-02-29',2)''')
        refresh_staffing(connection)
    result = reader(staffing, 1)._run(lambda connection, ids, _security: _resource_breakdown(
        connection, ids, date(2024, 1, 1), '2024-Q1', 1, 'overallocation'), [1])
    assert result['allocation']['2024-Q1'] == 9
    assert result['overallocation']['2024-Q1'] == 3
    assert result['peak_days']['allocation']['2024-Q1'] == '2024-02-29'
    assert result['peak_days']['allocation']['2024-Q2'] == '2024-04-01'
    assert result['consumers'] == [1]
