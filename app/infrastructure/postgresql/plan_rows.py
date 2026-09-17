"""Relational plan persistence with stable task identities across scenarios."""

import psycopg
from psycopg.rows import dict_row

from app.domain.planning.plans import PlanContent, PlanTask, PlanDependency, PlanTag
from app.domain.resources.models import PoolAssignment


def read_plans(connection: psycopg.Connection, plan_ids: list[int]) -> dict[int, PlanContent]:
    """Batch-load explicitly selected plans under project row security."""
    result = {row[0]: PlanContent() for row in connection.execute('SELECT id FROM eppm.project_plan WHERE id=ANY(%s::bigint[])', (plan_ids,))}
    with connection.cursor(row_factory=dict_row) as cursor:
        for row in cursor.execute('''SELECT project_plan_id,coalesce(stable_task_id,id) AS id,task_name,phase,start_date::text,end_date::text,description,coalesce(progress_pct,0) AS progress_pct
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
            JOIN eppm.active_resource_pool pool ON pool.id=a.pool_id
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


def write_plan(connection: psycopg.Connection, plan_id: int, project_id: int, content: PlanContent,
               *, previous: PlanContent | None = None) -> None:
    """Write plan-owned rows while retaining physical identities on scenario edits."""
    existing = {}
    changed_dependencies = {row['task_id'] for row in content.dependencies}
    changed_tags = set(content.task_tags)
    changed_assignments = True
    if previous is not None:
        existing = dict(connection.execute('SELECT coalesce(stable_task_id,id),id FROM eppm.project_task WHERE project_plan_id=%s', (plan_id,)))
        successors = {row['task_id'] for row in previous.dependencies + content.dependencies}
        changed_dependencies = {identity for identity in successors if
            [row for row in previous.dependencies if row['task_id'] == identity] !=
            [row for row in content.dependencies if row['task_id'] == identity]}
        changed_tags = {identity for identity in previous.task_tags.keys() | content.task_tags.keys()
                        if previous.task_tags.get(identity) != content.task_tags.get(identity)}
        changed_assignments = previous.assignments != content.assignments
        _clear_editable_children(connection, plan_id,
            [existing[key] for key in changed_dependencies if key in existing], None in changed_dependencies,
            [existing[key] for key in changed_tags if key in existing], changed_assignments)
        connection.execute('''UPDATE eppm.project_task SET is_deleted=true WHERE project_plan_id=%s
            AND NOT (coalesce(stable_task_id,id)=ANY(%s::bigint[]))''', (plan_id, [row['id'] for row in content.tasks]))
    own = {}
    for task in content.tasks:
        if task['id'] in existing:
            own[task['id']] = existing[task['id']]
            connection.execute('''UPDATE eppm.project_task SET task_name=%s,phase=%s,start_date=%s,
                end_date=%s,description=%s,progress_pct=%s,is_deleted=false WHERE id=%s AND project_plan_id=%s''',
                (task['task_name'], task['phase'], task['start_date'], task['end_date'], task['description'], task.get('progress_pct', 0), own[task['id']], plan_id))
            continue
        own[task['id']] = connection.execute('''INSERT INTO eppm.project_task(project_plan_id,stable_task_id,project_id,
            task_name,phase,start_date,end_date,description,progress_pct) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
            (plan_id, task['id'], project_id, task['task_name'], task['phase'], task['start_date'], task['end_date'], task['description'], task.get('progress_pct', 0))).fetchone()[0]
    external = {row['predecessor_task_id'] for row in content.dependencies if row['predecessor_task_id'] is not None} - own.keys()
    endpoints = {stable: identity for identity, stable in connection.execute('''SELECT t.id,coalesce(t.stable_task_id,t.id) FROM eppm.project_task t
        JOIN eppm.project_plan p ON p.id=t.project_plan_id WHERE coalesce(t.stable_task_id,t.id)=ANY(%s::bigint[])
        ORDER BY p.is_current,t.id''', (list(external),))}
    for row in content.dependencies:
        if row['task_id'] not in changed_dependencies:
            continue
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
        if task_id not in changed_tags:
            continue
        for tag in tags:
            connection.execute('INSERT INTO eppm.task_tag(task_id,tag_id,free_tag) VALUES(%s,%s,%s)', (own[task_id], tag['tag_id'], tag['free_tag']))
    for row in content.assignments if changed_assignments else []:
        connection.execute('''INSERT INTO eppm.resource_pool_assignment(project_plan_id,stable_assignment_id,pool_id,project_id,task_id,
            fte_assigned,start_date,end_date,notes,schedule_anchor,offset_days,duration_days) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (plan_id, row.id, row.pool_id, project_id, own.get(row.task_id), row.fte_assigned, row.start_date, row.end_date,
             row.notes, row.schedule_anchor, row.offset_days, row.duration_days))


def _clear_editable_children(connection: psycopg.Connection, plan_id: int, task_ids: list[int],
                             project_links: bool, tag_tasks: list[int], assignments: bool) -> None:
    """Replace visible plan-owned links only; retain inaccessible predecessors."""
    visible = '''(predecessor_task_id IN (SELECT id FROM eppm.project_task)
        OR predecessor_project_id IN (SELECT id FROM eppm.project))'''
    connection.execute(f'DELETE FROM eppm.task_dependencies WHERE task_id=ANY(%s::bigint[]) AND {visible}', (task_ids,))
    if project_links:
        connection.execute(f'DELETE FROM eppm.project_dependency WHERE project_plan_id=%s AND {visible}', (plan_id,))
    # The redacted dependency view identifies visible legacy primary links.
    connection.execute('''UPDATE eppm.project_task SET predecessor_id=NULL WHERE id=ANY(%s::bigint[])
        AND id IN (SELECT t.id FROM eppm.project_task t JOIN eppm.plan_row_dependencies d
            ON d.project_plan_id=t.project_plan_id AND d.task_id=coalesce(t.stable_task_id,t.id)
            JOIN eppm.project_task p ON p.id=d.predecessor_task_id)''', (task_ids,))
    connection.execute('DELETE FROM eppm.task_tag WHERE task_id=ANY(%s::bigint[])', (tag_tasks,))
    if assignments:
        connection.execute('DELETE FROM eppm.resource_pool_assignment WHERE project_plan_id=%s '
                           'AND pool_id IN (SELECT id FROM eppm.active_resource_pool)', (plan_id,))
