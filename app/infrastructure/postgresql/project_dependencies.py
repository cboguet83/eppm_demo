"""Scoped project dependency reads and explicit transactional link mutations."""

import psycopg
from psycopg.rows import dict_row

from app.application.exceptions import PlanningConflictError
from app.domain.planning.project_dependencies import ProjectDependency, ProjectDependencyInput, evaluate_project_dependencies


def read_project_dependencies(connection: psycopg.Connection, project_ids: list[int]) -> list[ProjectDependency]:
    """Read authorized links and batch aggregate endpoint bounds in one snapshot."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute('''WITH links AS MATERIALIZED (
            SELECT d.*,coalesce(d.predecessor_project_id,t.project_id) AS predecessor_owner_id
            FROM eppm.effective_project_dependency d LEFT JOIN eppm.current_project_task t ON t.id=d.predecessor_task_id
            WHERE d.project_id=ANY(%s::bigint[])
        ), bounds AS (
            SELECT project_id,min(start_date) AS first_date,max(end_date) AS last_date FROM eppm.current_project_task
            WHERE project_id IN (SELECT project_id FROM links UNION SELECT predecessor_owner_id FROM links)
            GROUP BY project_id
        ) SELECT d.*,p.name AS predecessor_project_name,t.task_name AS predecessor_task_name,
            to_char(CASE WHEN d.predecessor_task_id IS NULL THEN pred.first_date ELSE t.start_date END,'YYYY-MM-DD') AS pred_start_date,
            to_char(CASE WHEN d.predecessor_task_id IS NULL THEN pred.last_date ELSE t.end_date END,'YYYY-MM-DD') AS pred_end_date,
            to_char(own.first_date,'YYYY-MM-DD') AS start_date,to_char(own.last_date,'YYYY-MM-DD') AS end_date
        FROM links d JOIN eppm.project p ON p.id=d.predecessor_owner_id
        LEFT JOIN eppm.current_project_task t ON t.id=d.predecessor_task_id
        LEFT JOIN bounds pred ON pred.project_id=d.predecessor_owner_id
        LEFT JOIN bounds own ON own.project_id=d.project_id ORDER BY d.id''', (project_ids,)).fetchall()
    return evaluate_project_dependencies([ProjectDependency(**{key: value for key, value in row.items() if key != 'project_plan_id'}) for row in rows])


def project_dependency_revision(connection: psycopg.Connection, project_id: int) -> str:
    """Read a scoped source token including predecessor revisions and permissions."""
    row = connection.execute('SELECT source_token FROM eppm.planning_task_source_keys(ARRAY[%s]::bigint[])', (project_id,)).fetchone()
    if row is None:
        raise ValueError('The project is unavailable.')
    return row[0]


def write_project_dependencies(connection: psycopg.Connection, project_id: int,
                               upserts: list[ProjectDependencyInput], deleted_ids: list[int]) -> None:
    """Apply explicit changes only; inaccessible links cannot disappear on save."""
    for identity in deleted_ids:
        if connection.execute('DELETE FROM eppm.current_project_dependency WHERE id=%s AND project_id=%s', (identity, project_id)).rowcount != 1:
            raise PlanningConflictError('A dependency is no longer available. Reload the panel.')
    for row in upserts:
        values = (row['predecessor_project_id'], row['predecessor_task_id'], row['link_type'], row['lag_days'])
        if 'id' in row:
            if connection.execute('''UPDATE eppm.current_project_dependency SET predecessor_project_id=%s,predecessor_task_id=%s,
                link_type=%s,lag_days=%s WHERE id=%s AND project_id=%s''', (*values, row['id'], project_id)).rowcount != 1:
                raise PlanningConflictError('A dependency is no longer available. Reload the panel.')
        else:
            connection.execute('''INSERT INTO eppm.current_project_dependency
                (predecessor_project_id,predecessor_task_id,link_type,lag_days,project_id,project_plan_id)
                VALUES (%s,%s,%s,%s,%s,(SELECT id FROM eppm.project_plan WHERE project_id=%s AND is_current))''', (*values, project_id, project_id))
