"""Rebuild the current schedule projection without changing historical plan contents."""

import psycopg

from app.domain.planning.plans import PlanContent


def publish_current(connection: psycopg.Connection, project_id: int, content: PlanContent) -> None:
    """Apply the approved snapshot atomically while retaining live progress on matching tasks."""
    identities = [row['id'] for row in content.tasks]
    connection.execute('DELETE FROM eppm.resource_pool_assignment WHERE project_id=%s', (project_id,))
    connection.execute('DELETE FROM eppm.project_dependency WHERE project_id=%s', (project_id,))
    connection.execute('''DELETE FROM eppm.task_dependencies WHERE task_id IN
        (SELECT id FROM eppm.project_task WHERE project_id=%s)''', (project_id,))
    connection.execute('''DELETE FROM eppm.task_tag WHERE task_id IN
        (SELECT id FROM eppm.project_task WHERE project_id=%s)''', (project_id,))
    connection.execute('UPDATE eppm.project_task SET predecessor_id=NULL WHERE project_id=%s', (project_id,))
    connection.execute('DELETE FROM eppm.project_task WHERE project_id=%s AND NOT(id=ANY(%s::bigint[]))',
                        (project_id, identities))
    for row in content.tasks:
        connection.execute('''INSERT INTO eppm.project_task(id,project_id,task_name,phase,start_date,end_date,description)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET task_name=excluded.task_name,
            phase=excluded.phase,start_date=excluded.start_date,end_date=excluded.end_date,description=excluded.description''',
            (row['id'], project_id, row['task_name'], row['phase'], row['start_date'], row['end_date'], row['description']))
    for row in content.dependencies:
        predecessor = row['predecessor_task_id']
        if predecessor is not None and not connection.execute(
                'SELECT id FROM eppm.project_task WHERE id=%s', (predecessor,)).fetchone():
            # The immutable source retains the unresolved endpoint for comparison.
            continue
        if row['task_id'] is None:
            connection.execute('''INSERT INTO eppm.project_dependency
                (project_id,predecessor_task_id,predecessor_project_id,link_type,lag_days) VALUES(%s,%s,%s,%s,%s)''',
                (project_id, predecessor, row['predecessor_project_id'], row['link_type'], row['lag_days']))
        else:
            connection.execute('''INSERT INTO eppm.task_dependencies
                (task_id,predecessor_task_id,predecessor_project_id,link_type,lag_days) VALUES(%s,%s,%s,%s,%s)''',
                (row['task_id'], predecessor, row['predecessor_project_id'], row['link_type'], row['lag_days']))
    for identity, tags in content.task_tags.items():
        for tag in tags:
            connection.execute('INSERT INTO eppm.task_tag(task_id,tag_id) VALUES(%s,%s)', (identity, tag))
    for row in content.assignments:
        connection.execute('''INSERT INTO eppm.resource_pool_assignment
            (id,pool_id,project_id,task_id,fte_assigned,start_date,end_date,notes,schedule_anchor,offset_days,duration_days)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (row.id, row.pool_id, project_id, row.task_id, row.fte_assigned, row.start_date, row.end_date,
             row.notes, row.schedule_anchor, row.offset_days, row.duration_days))
