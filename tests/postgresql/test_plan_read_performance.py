"""Portfolio-sized relational plans retain bounded authorized source reads."""

import psycopg

from app.infrastructure.postgresql.business import run_business
from tests.postgresql.plan_fixtures import seed_test_plans


def test_portfolio_sources_with_primary_links_and_inactive_history(authorized, record_property):
    """Read 1,000 projects under the normal timeout, including primary links."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name) SELECT id,'Project '||id FROM generate_series(4,1000) id")
        seed_test_plans(connection)
        connection.execute("""INSERT INTO eppm.project_task
            (id,project_id,task_name,start_date,end_date,project_plan_id,predecessor_id)
            SELECT (p.project_id-1)*7+n,p.project_id,'Task '||n,'2026-01-01','2026-01-10',p.id,
                CASE WHEN n>1 THEN (p.project_id-1)*7+n-1 END
            FROM eppm.project_plan p CROSS JOIN generate_series(1,7) n WHERE p.is_current""")
        connection.execute("""INSERT INTO eppm.project_plan(project_id,version,name,status_id,author,created_at)
            SELECT id,2,'Inactive',3,'test',CURRENT_TIMESTAMP FROM eppm.project""")
        connection.execute("""INSERT INTO eppm.project_task
            (id,stable_task_id,project_id,task_name,start_date,end_date,project_plan_id)
            SELECT t.id+7000,t.id,t.project_id,t.task_name,t.start_date,t.end_date,p.id
            FROM eppm.project_task t JOIN eppm.project_plan p ON p.project_id=t.project_id AND NOT p.is_current""")
        connection.execute('ANALYZE eppm.project_task')
        connection.execute('ANALYZE eppm.project_plan')

    def inspect(connection):
        query = 'SELECT eppm.display_cache_revisions()'
        payload = connection.execute(query).fetchone()[0]
        assert len(payload['projects']) == 1000
        assert all(row[3] == [] for row in payload['projects'])
        plan = connection.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + query).fetchone()[0][0]
        record_property('revision_ms', plan['Execution Time'])
        blocks = plan['Plan']['Shared Hit Blocks'] + plan['Plan']['Shared Read Blocks']
        record_property('revision_blocks', blocks)
        # Repeated full permission/graph scans previously timed out on this size.
        assert blocks < 500_000
        assert connection.execute('SELECT count(*) FROM eppm.current_project_task').fetchone() == (7000,)

    run_business(authorized.database, authorized.key, authorized.binding(4).access, inspect)
