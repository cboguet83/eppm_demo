"""Measure the signed task-source query against unrelated graph growth."""

import psycopg
import pytest

from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.revisions import read_revisions, read_task_pool_pairs
from tests.postgresql.test_cache_key_plans import warm_cache_workload as warm_cache_workload
from tests.postgresql.test_revision_plans import revision_workload as revision_workload


def test_task_source_query_preserves_keys_without_scanning_unrelated_tasks(warm_cache_workload, record_property):
    fixture = warm_cache_workload
    access = fixture.binding(4).access
    query = 'SELECT * FROM eppm.planning_task_source_keys(ARRAY[2]::bigint[])'

    def inspect(connection):
        expected = read_revisions(connection, access).task_tokens([2], read_task_pool_pairs(connection, [2]))
        for _ in range(8):
            assert dict(connection.execute(query).fetchall()) == expected
        plan = connection.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + query).fetchone()[0][0]
        return expected, plan

    before, initial = run_business(fixture.database, fixture.key, access, inspect)
    with psycopg.connect(fixture.setup.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date)
            SELECT id,3,'Unrelated','2026-01-01','2026-01-02' FROM generate_series(70008,75007) id""")
        connection.execute("""INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id)
            SELECT id,15 FROM eppm.project_task WHERE id>=70008""")
        connection.execute('ANALYZE eppm.project_task')
        connection.execute('ANALYZE eppm.task_dependencies')
    with psycopg.connect(fixture.setup.operator_url, autocommit=True) as connection:
        connection.execute('VACUUM (ANALYZE) eppm.project_cache_revision')
    after, final = run_business(fixture.database, fixture.key, access, inspect)
    assert after == before
    blocks = []
    for name, plan in (('before', initial), ('after', final)):
        blocks.append(plan['Plan']['Shared Hit Blocks'] + plan['Plan']['Shared Read Blocks'])
        record_property(name + '_task_source_blocks', blocks[-1])
        record_property(name + '_task_source_ms', plan['Execution Time'])
    assert blocks[1] <= blocks[0] + 64, blocks


@pytest.mark.parametrize('selection', [None, [], [1] * 26, [None]])
def test_runtime_cannot_expand_an_unbounded_task_source_batch(authorized, selection):
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        authorized.query('SELECT * FROM eppm.planning_task_source_keys(%s::bigint[])', (selection,), user_id=4)
