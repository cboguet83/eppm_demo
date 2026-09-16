"""Frozen migration 0045: retain live work and expand every saved JSON snapshot."""

import re

import psycopg
from psycopg import sql


TABLES = ('project_task', 'resource_pool_assignment', 'task_dependencies', 'task_tag', 'project_dependency')


def convert_plans(connection: psycopg.Connection) -> None:
    """Convert history and live rows atomically without discarding divergent work."""
    plans = connection.execute('SELECT id,project_id,content,is_current,is_baseline FROM eppm.project_plan ORDER BY id').fetchall()
    for table, collection in (('project_task', 'tasks'), ('resource_pool_assignment', 'assignments')):
        historical = max((row['id'] or 0 for _, _, content, _, _ in plans for row in content[collection]), default=0)
        existing = connection.execute(sql.SQL('SELECT coalesce(max(id),0) FROM eppm.{}').format(sql.Identifier(table))).fetchone()[0]
        consumed = connection.execute("SELECT last_value FROM pg_sequences WHERE schemaname='eppm' AND sequencename=%s", (table + '_id_seq',)).fetchone()[0]
        maximum = max(existing, historical, consumed or 0)
        connection.execute("SELECT setval(pg_get_serial_sequence(%s,'id'),%s,%s)", ('eppm.' + table, max(maximum, 1), maximum > 0))
    connection.execute('UPDATE eppm.project_task SET stable_task_id=id')
    connection.execute('UPDATE eppm.resource_pool_assignment SET stable_assignment_id=id')
    for project_id, in connection.execute('SELECT id FROM eppm.project ORDER BY id').fetchall():
        connection.execute('''INSERT INTO eppm.project_plan_event(project_id,plan_id,action,old_value,new_value,author,created_at)
            SELECT project_id,id,'current','true','false','migration:0045',CURRENT_TIMESTAMP
            FROM eppm.project_plan WHERE project_id=%s AND is_current''', (project_id,))
        connection.execute('UPDATE eppm.project_plan SET is_current=false WHERE project_id=%s', (project_id,))
        plan_id = connection.execute('''INSERT INTO eppm.project_plan(project_id,version,name,status_id,is_current,author,created_at)
            SELECT %s,coalesce(max(version),0)+1,'Current working plan',3,true,'migration:0045',CURRENT_TIMESTAMP
            FROM eppm.project_plan WHERE project_id=%s RETURNING id''', (project_id, project_id)).fetchone()[0]
        for table in ('project_task', 'resource_pool_assignment', 'project_dependency'):
            connection.execute(sql.SQL('UPDATE eppm.{} SET project_plan_id=%s WHERE project_id=%s').format(sql.Identifier(table)), (plan_id, project_id))
        connection.execute("INSERT INTO eppm.project_plan_event(project_id,plan_id,action,new_value,author,created_at) VALUES(%s,%s,'created','approved','migration:0045',CURRENT_TIMESTAMP)", (project_id, plan_id))
    # Insert all task versions before resolving dependencies between projects.
    maps = {}
    for plan_id, project_id, content, _, baseline in plans:
        maps[plan_id] = {}
        connection.execute('''UPDATE eppm.project_plan SET is_frozen=%s OR EXISTS
            (SELECT 1 FROM eppm.project_plan_event WHERE plan_id=%s AND action='baseline' AND new_value='true')
            WHERE id=%s''', (baseline, plan_id, plan_id))
        for task in content['tasks']:
            row = connection.execute('''INSERT INTO eppm.project_task(project_plan_id,stable_task_id,project_id,task_name,phase,start_date,end_date,description,progress_pct)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,coalesce((SELECT progress_pct FROM eppm.plan_task_actual WHERE task_id=%s),0)) RETURNING id''',
                (plan_id, task['id'], project_id, task['task_name'], task['phase'], task['start_date'], task['end_date'], task['description'], task['id'])).fetchone()[0]
            maps[plan_id][task['id']] = row
    endpoints = {}
    for identity, stable in connection.execute('''SELECT t.id,t.stable_task_id FROM eppm.project_task t
        JOIN eppm.project_plan p ON p.id=t.project_plan_id ORDER BY p.is_current,t.id'''):
        endpoints[stable] = identity
    for plan_id, project_id, content, _, _ in plans:
        own = maps[plan_id]
        for dep in content['dependencies']:
            predecessor = dep['predecessor_task_id']
            predecessor = own.get(predecessor, endpoints.get(predecessor)) if predecessor is not None else None
            if predecessor is None and dep['predecessor_project_id'] is None:
                raise ValueError('A historical dependency has no retained task identity.')
            if dep['task_id'] is None:
                connection.execute('''INSERT INTO eppm.project_dependency(project_plan_id,project_id,predecessor_task_id,predecessor_project_id,link_type,lag_days)
                    VALUES(%s,%s,%s,%s,%s,%s)''', (plan_id, project_id, predecessor, dep['predecessor_project_id'], dep['link_type'], dep['lag_days']))
            else:
                connection.execute('INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id,predecessor_project_id,link_type,lag_days) VALUES(%s,%s,%s,%s,%s)',
                    (own[dep['task_id']], predecessor, dep['predecessor_project_id'], dep['link_type'], dep['lag_days']))
        for task_id, tags in content['task_tags'].items():
            for tag in tags:
                connection.execute('INSERT INTO eppm.task_tag(task_id,tag_id,free_tag) VALUES(%s,%s,%s)', (own[int(task_id)], tag['tag_id'], tag['free_tag']))
        for assignment in content['assignments']:
            connection.execute('''INSERT INTO eppm.resource_pool_assignment(project_plan_id,stable_assignment_id,pool_id,project_id,task_id,
                fte_assigned,start_date,end_date,notes,schedule_anchor,offset_days,duration_days) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (plan_id, assignment['id'], assignment['pool_id'], project_id, own.get(assignment['task_id']), assignment['fte_assigned'],
                 assignment['start_date'], assignment['end_date'], assignment['notes'], assignment.get('schedule_anchor'), assignment.get('offset_days'), assignment.get('duration_days')))
    # Validate deferred dependency references before schema changes on populated tables.
    connection.execute('SET CONSTRAINTS ALL IMMEDIATE')
    connection.execute('ALTER TABLE eppm.project_plan DROP COLUMN content')
    for table in ('project_task', 'resource_pool_assignment', 'project_dependency'):
        connection.execute(sql.SQL('ALTER TABLE eppm.{} ALTER COLUMN project_plan_id SET NOT NULL').format(sql.Identifier(table)))
    _active_views(connection)
    _task_edit_access(connection)
    for table in TABLES:
        owner = 'project_plan_id' if table not in ('task_dependencies', 'task_tag') else '(SELECT project_plan_id FROM eppm.project_task WHERE id=task_id AND NOT is_deleted)'
        predicate = sql.SQL('{} IN (SELECT id FROM eppm.project_plan WHERE NOT is_frozen AND status_id<>5)').format(sql.SQL(owner))
        for action in ('INSERT', 'UPDATE', 'DELETE'):
            clause = sql.SQL('WITH CHECK ({})').format(predicate) if action == 'INSERT' else sql.SQL('USING ({})').format(predicate)
            connection.execute(sql.SQL('CREATE POLICY {} ON eppm.{} AS RESTRICTIVE FOR {} TO eppm_runtime {}').format(
                sql.Identifier('editable_plan_' + action.lower()), sql.Identifier(table), sql.SQL(action), clause))


def _active_views(connection: psycopg.Connection) -> None:
    """Centralize selection and retarget existing read-only SQL projections."""
    for table in TABLES:
        if table == 'project_task':
            columns = [row[0] for row in connection.execute("SELECT attname FROM pg_attribute WHERE attrelid='eppm.project_task'::regclass AND attnum>0 AND NOT attisdropped ORDER BY attnum")]
            expressions = [sql.SQL("CASE WHEN t.predecessor_id IS NULL THEN NULL WHEN eppm.runtime_session() THEN (SELECT access.predecessor_id FROM eppm.plan_task_edit_access access WHERE access.id=t.id) ELSE t.predecessor_id END AS predecessor_id")
                           if column == 'predecessor_id' else sql.SQL('t.{}').format(sql.Identifier(column)) for column in columns]
            connection.execute(sql.SQL('CREATE VIEW eppm.current_project_task WITH(security_barrier=true) AS SELECT {} FROM eppm.project_task t WHERE NOT t.is_deleted AND project_plan_id IN (SELECT id FROM eppm.project_plan WHERE is_current) AND (CASE WHEN eppm.runtime_session() THEN project_id=ANY(eppm.permission_projects(\'project.read\')) ELSE true END)').format(sql.SQL(',').join(expressions)))
            # This redacted definer view is read-only for runtime actors.
            # Python writes the base table under its existing RLS policies.
            connection.execute('GRANT SELECT ON eppm.current_project_task TO eppm_runtime')
            continue
        owner = 'project_plan_id' if table not in ('task_dependencies', 'task_tag') else '(SELECT project_plan_id FROM eppm.project_task WHERE id=task_id AND NOT is_deleted)'
        existing_task = ' AND (task_id IS NULL OR task_id IN (SELECT id FROM eppm.project_task WHERE NOT is_deleted))' if table == 'resource_pool_assignment' else ''
        connection.execute(sql.SQL('CREATE VIEW eppm.{} WITH(security_invoker=true) AS SELECT * FROM eppm.{} WHERE {} IN (SELECT id FROM eppm.project_plan WHERE is_current) {} WITH LOCAL CHECK OPTION').format(
            sql.Identifier('current_' + table), sql.Identifier(table), sql.SQL(owner), sql.SQL(existing_task)))
        connection.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON eppm.{} TO eppm_runtime').format(sql.Identifier('current_' + table)))
    for table in ('task_dependencies', 'project_dependency'):
        columns = [row[0] for row in connection.execute("SELECT attname FROM pg_attribute WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped ORDER BY attnum", ('eppm.' + table,))]
        expressions = [sql.SQL('coalesce(active.id,d.predecessor_task_id) AS predecessor_task_id') if column == 'predecessor_task_id'
                       else sql.SQL('d.{}').format(sql.Identifier(column)) for column in columns]
        connection.execute(sql.SQL('CREATE VIEW eppm.{} WITH(security_invoker=true) AS SELECT {} FROM eppm.{} d LEFT JOIN eppm.project_task original ON original.id=d.predecessor_task_id LEFT JOIN eppm.current_project_task active ON coalesce(active.stable_task_id,active.id)=coalesce(original.stable_task_id,original.id)').format(
            sql.Identifier('effective_' + table), sql.SQL(',').join(expressions), sql.Identifier('current_' + table)))
        connection.execute(sql.SQL('GRANT SELECT ON eppm.{} TO eppm_runtime').format(sql.Identifier('effective_' + table)))
    # Existing SQL read helpers keep their calculations. Only the row source changes.
    readers = ('dashboard_revision', 'dashboard_resources', 'current_cache_keys', 'display_cache_revisions', 'planning_task_source_keys')
    for identity, definition in connection.execute('''SELECT p.oid::regprocedure::text,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='eppm' AND p.proname=ANY(%s)''', (list(readers),)).fetchall():
        connection.execute(_scope(definition))
        connection.execute(sql.SQL('ALTER FUNCTION {} SET search_path=pg_catalog,eppm,pg_temp').format(sql.SQL(identity)))
    for name, definition in connection.execute('''SELECT viewname,definition FROM pg_views WHERE schemaname='eppm'
        AND viewname NOT LIKE 'current_%%' AND viewname NOT LIKE 'effective_%%'
        AND viewname NOT LIKE 'plan_row_%%' AND viewname<>'plan_task_edit_access' ''').fetchall():
        scoped = _scope(definition)
        if scoped != definition:
            connection.execute(sql.SQL('CREATE OR REPLACE VIEW eppm.{} AS ').format(sql.Identifier(name)) + sql.SQL(scoped))


def _scope(source: str) -> str:
    result = re.sub(r'eppm\.(project_task|resource_pool_assignment|task_dependencies|task_tag|project_dependency)\b', r'eppm.current_\1', source)
    result = re.sub(r'\b(FROM|JOIN)\s+(project_task|resource_pool_assignment|task_dependencies|task_tag|project_dependency)\b', r'\1 eppm.current_\2', result, flags=re.IGNORECASE)
    result = re.sub(r'\b(project_task|resource_pool_assignment|task_dependencies|task_tag|project_dependency)\.', r'current_\1.', result)
    return result.replace('current_task_dependencies', 'effective_task_dependencies').replace('current_project_dependency', 'effective_project_dependency')


def _task_edit_access(connection: psycopg.Connection) -> None:
    """Check protected consumers without redacting the definer's security input."""
    connection.execute('''CREATE OR REPLACE VIEW eppm.plan_task_edit_access WITH(security_barrier=true) AS
        SELECT task.id,
            NOT EXISTS(SELECT 1 FROM eppm.task_dependencies d
                JOIN eppm.project_task consumer ON consumer.id=d.task_id
                JOIN eppm.project_task original ON original.id=d.predecessor_task_id
                WHERE coalesce(original.stable_task_id,original.id)=coalesce(task.stable_task_id,task.id)
                AND NOT consumer.is_deleted AND consumer.project_plan_id IN
                    (SELECT id FROM eppm.project_plan WHERE is_current)
                AND NOT consumer.project_id=ANY(eppm.permission_projects('project.edit')))
            AND NOT EXISTS(SELECT 1 FROM eppm.project_task consumer
                JOIN eppm.project_task original ON original.id=consumer.predecessor_id
                WHERE coalesce(original.stable_task_id,original.id)=coalesce(task.stable_task_id,task.id)
                AND NOT consumer.is_deleted AND consumer.project_plan_id IN
                    (SELECT id FROM eppm.project_plan WHERE is_current)
                AND NOT consumer.project_id=ANY(eppm.permission_projects('project.edit')))
            AND NOT EXISTS(SELECT 1 FROM eppm.task_dependencies d
                LEFT JOIN eppm.project_task predecessor ON predecessor.id=d.predecessor_task_id
                WHERE d.task_id=task.id AND NOT coalesce(d.predecessor_project_id,predecessor.project_id)
                    =ANY(eppm.permission_projects('project.edit'))) AS removable,
            task.predecessor_id IS NULL OR original.project_id=ANY(eppm.permission_projects('project.edit'))
                AS predecessor_editable,
            CASE WHEN original.project_id=ANY(eppm.permission_projects('project.read'))
                THEN coalesce(active.id,task.predecessor_id) END AS predecessor_id
        FROM eppm.project_task task LEFT JOIN eppm.project_task original ON original.id=task.predecessor_id
        LEFT JOIN eppm.project_task active ON coalesce(active.stable_task_id,active.id)=coalesce(original.stable_task_id,original.id)
            AND NOT active.is_deleted AND active.project_plan_id IN (SELECT id FROM eppm.project_plan WHERE is_current)
        WHERE NOT task.is_deleted AND task.project_plan_id IN (SELECT id FROM eppm.project_plan WHERE is_current)
            AND task.project_id=ANY(eppm.permission_projects('project.read'))''')
