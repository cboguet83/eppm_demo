"""Persist compact project summaries; invalidate only projects whose warnings change."""


def install_summary_cache(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS planning_summary_cache (
        project_id INTEGER PRIMARY KEY REFERENCES project(id) ON DELETE CASCADE,
        name TEXT,start TEXT,end TEXT,task_count INTEGER,progress REAL,has_violations INTEGER)''')
    for table in ('project_task', 'task_dependencies', 'project'):
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            refs = ('OLD', 'NEW') if event == 'UPDATE' else ('OLD',) if event == 'DELETE' else ('NEW',)
            queries = []
            for ref in refs:
                if table == 'project':
                    queries.append(f'SELECT {ref}.id')
                elif table == 'task_dependencies':
                    queries.append(f'SELECT project_id FROM project_task WHERE id={ref}.task_id')
                else:
                    queries.append(f'SELECT {ref}.project_id')
                    queries.append(f'''SELECT t.project_id FROM task_dependencies d JOIN project_task t ON t.id=d.task_id
                        WHERE d.predecessor_task_id={ref}.id OR d.predecessor_project_id={ref}.project_id''')
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS planning_summary_{table}_{event.lower()}
                BEFORE {event} ON {table} BEGIN DELETE FROM planning_summary_cache WHERE project_id IN
                ({' UNION '.join(queries)}); END''')
