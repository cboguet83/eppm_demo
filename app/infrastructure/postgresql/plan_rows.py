"""Relational plan persistence with stable task identities across scenarios."""

import psycopg
from psycopg.rows import dict_row

from app.domain.planning.plans import PlanContent, PlanTask, PlanDependency, PlanTag
from app.domain.resources.models import PoolAssignment


def read_plans(connection: psycopg.Connection, plan_ids: list[int]) -> dict[int, PlanContent]:
    """Batch-load explicitly selected plans under project row security."""
    result = {row[0]: PlanContent() for row in connection.execute('SELECT id FROM eppm.project_plan WHERE id=ANY(%s::bigint[])', (plan_ids,))}
    with connection.cursor(row_factory=dict_row) as cursor:
        for row in cursor.execute('''SELECT project_plan_id,coalesce(stable_task_id,id) AS id,task_name,phase,start_date::text,end_date::text,description
            FROM eppm.project_task WHERE NOT is_deleted AND project_plan_id=ANY(%s::bigint[]) ORDER BY id''', (list(result),)):
            result[row.pop('project_plan_id')].tasks.append(PlanTask(**row))
        for row in cursor.execute('''SELECT t.project_plan_id,coalesce(t.stable_task_id,t.id) AS task_id,
            coalesce(p.stable_task_id,p.id) AS predecessor_task_id,d.predecessor_project_id,d.link_type,d.lag_days
            FROM eppm.task_dependencies d JOIN eppm.project_task t ON t.id=d.task_id
            LEFT JOIN eppm.project_task p ON p.id=d.predecessor_task_id WHERE NOT t.is_deleted AND t.project_plan_id=ANY(%s::bigint[])
            UNION ALL SELECT d.project_plan_id,NULL,coalesce(p.stable_task_id,p.id),d.predecessor_project_id,d.link_type,d.lag_days
            FROM eppm.project_dependency d LEFT JOIN eppm.project_task p ON p.id=d.predecessor_task_id WHERE d.project_plan_id=ANY(%s::bigint[])''', (list(result), list(result))):
            content = result[row.pop('project_plan_id')]
            if row['predecessor_task_id'] is not None or row['predecessor_project_id'] is not None:
                content.dependencies.append(PlanDependency(**row))
        for row in cursor.execute('''SELECT a.project_plan_id,coalesce(a.stable_assignment_id,a.id) AS id,a.pool_id,a.project_id,
            coalesce(t.stable_task_id,t.id) AS task_id,a.fte_assigned::float,a.start_date::text,a.end_date::text,a.notes,
            a.schedule_anchor,a.offset_days,a.duration_days FROM eppm.resource_pool_assignment a
            LEFT JOIN eppm.project_task t ON t.id=a.task_id WHERE a.project_plan_id=ANY(%s::bigint[])
            AND (a.task_id IS NULL OR NOT t.is_deleted) ORDER BY a.id''', (list(result),)):
            result[row.pop('project_plan_id')].assignments.append(PoolAssignment(**row))
    for plan_id, task_id, tag_id, free_tag in connection.execute('''SELECT t.project_plan_id,coalesce(t.stable_task_id,t.id),tt.tag_id,tt.free_tag
        FROM eppm.task_tag tt JOIN eppm.project_task t ON t.id=tt.task_id WHERE NOT t.is_deleted AND t.project_plan_id=ANY(%s::bigint[])''', (list(result),)):
        result[plan_id].task_tags.setdefault(task_id, []).append(PlanTag(tag_id=tag_id, free_tag=free_tag))
    direct = connection.execute("SELECT has_column_privilege(current_user,'eppm.project_task','predecessor_id','SELECT')").fetchone()[0]
    primary_links = '''SELECT t.project_plan_id,coalesce(t.stable_task_id,t.id),coalesce(p.stable_task_id,p.id)
        FROM eppm.project_task t JOIN eppm.project_task p ON p.id=t.predecessor_id
        WHERE NOT t.is_deleted AND t.project_plan_id=ANY(%s::bigint[])''' if direct else '''
        SELECT d.project_plan_id,d.task_id,coalesce(p.stable_task_id,p.id)
        FROM eppm.plan_row_dependencies d JOIN eppm.project_task p ON p.id=d.predecessor_task_id
        WHERE d.task_id IS NOT NULL AND d.project_plan_id=ANY(%s::bigint[])'''
    for plan_id, task_id, predecessor in connection.execute(primary_links, (list(result),)):
        dependencies = result[plan_id].dependencies
        if not any(row['task_id'] == task_id and row['predecessor_task_id'] == predecessor for row in dependencies):
            dependencies.append(PlanDependency(task_id=task_id, predecessor_task_id=predecessor, predecessor_project_id=None, link_type='FS', lag_days=0))
    return result


def copy_protected_links(connection: psycopg.Connection, source: int, target: int) -> None:
    """Retain inaccessible source endpoints without exposing them in public DTOs.

    The scoped view reveals only links owned by readable plans, as the former
    snapshot did. Insert policies require an exact source-link match; callers
    cannot introduce a new inaccessible endpoint through this path.
    """
    hidden = '''(d.predecessor_task_id IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM eppm.project_task WHERE id=d.predecessor_task_id))
        OR (d.predecessor_project_id IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM eppm.project WHERE id=d.predecessor_project_id))'''
    connection.execute(f'''INSERT INTO eppm.task_dependencies
        (task_id,predecessor_task_id,predecessor_project_id,link_type,lag_days)
        SELECT t.id,d.predecessor_task_id,d.predecessor_project_id,d.link_type,d.lag_days
        FROM eppm.plan_row_dependencies d JOIN eppm.project_task t
        ON coalesce(t.stable_task_id,t.id)=d.task_id AND t.project_plan_id=%s
        WHERE d.project_plan_id=%s AND ({hidden})''', (target, source))
    connection.execute(f'''INSERT INTO eppm.project_dependency
        (project_plan_id,project_id,predecessor_task_id,predecessor_project_id,link_type,lag_days)
        SELECT p.id,p.project_id,d.predecessor_task_id,d.predecessor_project_id,d.link_type,d.lag_days
        FROM eppm.plan_row_dependencies d JOIN eppm.project_plan p ON p.id=%s
        WHERE d.project_plan_id=%s AND d.task_id IS NULL AND ({hidden})''', (target, source))


def write_plan(connection: psycopg.Connection, plan_id: int, project_id: int, content: PlanContent) -> None:
    """Insert independent task/assignment rows and map their stable endpoints."""
    connection.execute('''INSERT INTO eppm.plan_task_actual(task_id,project_id,progress_pct)
        SELECT coalesce(stable_task_id,id),project_id,coalesce(progress_pct,0)
        FROM eppm.current_project_task WHERE project_id=%s ON CONFLICT(task_id) DO NOTHING''', (project_id,))
    own = {}
    for task in content.tasks:
        own[task['id']] = connection.execute('''INSERT INTO eppm.project_task(project_plan_id,stable_task_id,project_id,
            task_name,phase,start_date,end_date,description,progress_pct) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,
            coalesce((SELECT progress_pct FROM eppm.plan_task_actual WHERE task_id=%s),0)) RETURNING id''',
            (plan_id, task['id'], project_id, task['task_name'], task['phase'], task['start_date'], task['end_date'], task['description'], task['id'])).fetchone()[0]
    external = {row['predecessor_task_id'] for row in content.dependencies if row['predecessor_task_id'] is not None} - own.keys()
    endpoints = {stable: identity for identity, stable in connection.execute('''SELECT t.id,coalesce(t.stable_task_id,t.id) FROM eppm.project_task t
        JOIN eppm.project_plan p ON p.id=t.project_plan_id WHERE coalesce(t.stable_task_id,t.id)=ANY(%s::bigint[])
        ORDER BY p.is_current,t.id''', (list(external),))}
    for row in content.dependencies:
        stable = row['predecessor_task_id']
        predecessor = own.get(stable, endpoints.get(stable))
        if stable is not None and predecessor is None:
            raise ValueError('A dependency task is no longer available in the selected scope.')
        if row['task_id'] is None:
            connection.execute('''INSERT INTO eppm.project_dependency(project_plan_id,project_id,predecessor_task_id,predecessor_project_id,link_type,lag_days)
                VALUES(%s,%s,%s,%s,%s,%s)''', (plan_id, project_id, predecessor, row['predecessor_project_id'], row['link_type'], row['lag_days']))
        else:
            connection.execute('INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id,predecessor_project_id,link_type,lag_days) VALUES(%s,%s,%s,%s,%s)',
                (own[row['task_id']], predecessor, row['predecessor_project_id'], row['link_type'], row['lag_days']))
    for task_id, tags in content.task_tags.items():
        for tag in tags:
            connection.execute('INSERT INTO eppm.task_tag(task_id,tag_id,free_tag) VALUES(%s,%s,%s)', (own[task_id], tag['tag_id'], tag['free_tag']))
    for row in content.assignments:
        connection.execute('''INSERT INTO eppm.resource_pool_assignment(project_plan_id,stable_assignment_id,pool_id,project_id,task_id,
            fte_assigned,start_date,end_date,notes,schedule_anchor,offset_days,duration_days) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (plan_id, row.id, row.pool_id, project_id, own.get(row.task_id), row.fte_assigned, row.start_date, row.end_date,
             row.notes, row.schedule_anchor, row.offset_days, row.duration_days))
