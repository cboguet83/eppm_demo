"""Explicit active plans for operator-created project fixtures."""

import psycopg


def seed_test_plans(connection: psycopg.Connection) -> None:
    """Mirror normal project creation without changing production constraints."""
    connection.execute('''INSERT INTO eppm.project_plan
        (project_id,version,name,status_id,is_current,author,created_at)
        SELECT p.id,1,'Initial plan',3,true,'test setup',CURRENT_TIMESTAMP
        FROM eppm.project p WHERE NOT EXISTS
            (SELECT 1 FROM eppm.project_plan plan WHERE plan.project_id=p.id)''')
