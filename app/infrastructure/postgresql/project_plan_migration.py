"""Capture initial approved current plans using Python inside migration 0041."""

from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb

from app.infrastructure.postgresql.plan_content import capture_content, encode_content


def capture_initial_plans(connection: psycopg.Connection) -> None:
    """Preserve existing schedules atomically; baseline remains unset."""
    for project_id, in connection.execute('SELECT id FROM eppm.project ORDER BY id').fetchall():
        connection.execute('''INSERT INTO eppm.project_plan
            (project_id,version,name,status_id,is_current,author,created_at,content)
            VALUES(%s,1,'Initial plan',3,true,'migration:0041',%s,%s)''',
            (project_id, datetime.now(timezone.utc), Jsonb(encode_content(capture_content(connection, project_id)))))
