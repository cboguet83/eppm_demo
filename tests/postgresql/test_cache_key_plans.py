"""Selected cache keys avoid expanding every portfolio dependency and revision."""

from datetime import date

import psycopg
import pytest

from app.infrastructure.postgresql.business import run_business
from tests.postgresql.test_revision_plans import revision_workload as revision_workload


@pytest.fixture
def warm_cache_workload(revision_workload):
    """Remove bulk-seed row versions before measuring repeatable warm query work."""
    with psycopg.connect(revision_workload.setup.operator_url, autocommit=True) as connection:
        connection.execute('VACUUM (ANALYZE) eppm.project_cache_revision')
    return revision_workload


@pytest.mark.parametrize('kind', ['planning', 'capacity'])
def test_selected_cache_work_does_not_grow_with_unrelated_tasks(warm_cache_workload, record_property, kind):
    query = 'SELECT * FROM eppm.read_derived_cache(%s,%s::bigint[],%s,1,false,ARRAY[]::text[])'

    def inspect(connection: psycopg.Connection) -> dict:
        parameters = (kind, None, date(2026, 1, 3))
        full = connection.execute(query, parameters).fetchall()
        full_plan = connection.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + query, parameters).fetchone()[0][0]
        parameters = (kind, [2], date(2026, 1, 3))
        selected = connection.execute(query, parameters).fetchall()
        assert selected == [row for row in full if row[0] == 2]
        for _ in range(6):
            assert connection.execute(query, parameters).fetchall() == selected
        selected_plan = connection.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + query, parameters).fetchone()[0][0]
        return {'full': full_plan, 'selected': selected_plan}, selected

    fixture = warm_cache_workload
    plans, expected = run_business(fixture.database, fixture.key, fixture.binding(4).access, inspect)
    with psycopg.connect(fixture.setup.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date)
            SELECT id,3,'Unrelated','2026-01-01','2026-01-02' FROM generate_series(70008,75007) id""")
        connection.execute("""INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id)
            SELECT id,15 FROM eppm.project_task WHERE id>=70008""")
        connection.execute('ANALYZE eppm.project_task')
        connection.execute('ANALYZE eppm.task_dependencies')
    with psycopg.connect(fixture.setup.operator_url, autocommit=True) as connection:
        connection.execute('VACUUM (ANALYZE) eppm.project_cache_revision')

    def inspect_after(connection: psycopg.Connection) -> dict:
        parameters = (kind, [2], date(2026, 1, 3))
        assert connection.execute(query, parameters).fetchall() == expected
        return connection.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + query, parameters).fetchone()[0][0]

    plans['after_unrelated_tasks'] = run_business(fixture.database, fixture.key, fixture.binding(4).access, inspect_after)
    blocks = {name: plan['Plan']['Shared Hit Blocks'] + plan['Plan']['Shared Read Blocks']
              for name, plan in plans.items()}
    for name, plan in plans.items():
        record_property(name + '_cache_ms', plan['Execution Time'])
        record_property(name + '_cache_blocks', blocks[name])
    # The visible project membership is unchanged. Allow small index/planner
    # differences, but not reading 5,000 new unrelated tasks and dependencies.
    # Full bulk reads can use sequential scans more efficiently than individual
    # index lookups, so their buffer count is diagnostic, not a ratio target.
    assert blocks['after_unrelated_tasks'] <= blocks['selected'] + 64, blocks
