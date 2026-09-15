"""Capture initial approved current plans using Python inside migration 0041."""

from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def _snapshot(connection: psycopg.Connection, project_id: int) -> dict:
    """Frozen migration representation; independent of evolving runtime codecs."""
    with connection.cursor(row_factory=dict_row) as cursor:
        tasks = list(cursor.execute('''SELECT id,task_name,phase,to_char(start_date,'YYYY-MM-DD') AS start_date,
            to_char(end_date,'YYYY-MM-DD') AS end_date,description FROM eppm.project_task WHERE project_id=%s ORDER BY id''', (project_id,)))
        dependencies = list(cursor.execute('''SELECT d.task_id,d.predecessor_task_id,d.predecessor_project_id,d.link_type,d.lag_days
            FROM eppm.task_dependencies d JOIN eppm.project_task t ON t.id=d.task_id WHERE t.project_id=%s
            UNION ALL SELECT NULL,predecessor_task_id,predecessor_project_id,link_type,lag_days
            FROM eppm.project_dependency WHERE project_id=%s''', (project_id, project_id)))
        for row in cursor.execute('''SELECT id AS task_id,predecessor_id AS predecessor_task_id,
            NULL::bigint AS predecessor_project_id,'FS' AS link_type,0 AS lag_days
            FROM eppm.project_task WHERE project_id=%s AND predecessor_id IS NOT NULL''', (project_id,)):
            if not any(dep['task_id'] == row['task_id'] and dep['predecessor_task_id'] == row['predecessor_task_id'] for dep in dependencies):
                dependencies.append(row)
        assignments = list(cursor.execute('''SELECT id,pool_id,project_id,task_id,fte_assigned::float,
            to_char(start_date,'YYYY-MM-DD') AS start_date,to_char(end_date,'YYYY-MM-DD') AS end_date,
            notes,schedule_anchor,offset_days,duration_days FROM eppm.resource_pool_assignment WHERE project_id=%s ORDER BY id''', (project_id,)))
        tags = {}
        for row in cursor.execute('''SELECT tt.task_id,tt.tag_id,tt.free_tag FROM eppm.task_tag tt
            JOIN eppm.project_task t ON t.id=tt.task_id WHERE t.project_id=%s''', (project_id,)):
            tags.setdefault(str(row['task_id']), []).append({'tag_id': row['tag_id'], 'free_tag': row['free_tag']})
    return dict(tasks=tasks, dependencies=dependencies, assignments=assignments, task_tags=tags)


def capture_initial_plans(connection: psycopg.Connection) -> None:
    """Preserve existing schedules atomically; baseline remains unset."""
    for project_id, in connection.execute('SELECT id FROM eppm.project ORDER BY id').fetchall():
        connection.execute('''INSERT INTO eppm.project_plan
            (project_id,version,name,status_id,is_current,author,created_at,content)
            VALUES(%s,1,'Initial plan',3,true,'migration:0041',%s,%s)''',
            (project_id, datetime.now(timezone.utc), Jsonb(_snapshot(connection, project_id))))
