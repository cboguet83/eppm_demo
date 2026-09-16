"""Protect current plan projections from legacy direct editing commands."""

import psycopg
from app.domain.access.models import AccessDenied


def require_reschedule(connection: psycopg.Connection, task_id: int) -> int | None:
    """Authorize live date edits and serialize them with baseline capture."""
    row = connection.execute('SELECT project_id FROM eppm.project_task WHERE id=%s', (task_id,)).fetchone()
    if row is None:
        return None
    project_id = row[0]
    if not connection.execute("SELECT %s=ANY(eppm.permission_projects('project.edit'))", (project_id,)).fetchone()[0]:
        raise AccessDenied()
    connection.execute('SELECT id FROM eppm.project WHERE id=%s FOR UPDATE', (project_id,))
    return project_id


def require_unversioned(connection: psycopg.Connection, *, project_id: int | None = None,
                        task_id: int | None = None) -> None:
    """Direct callers must use a draft once a project has an immutable current plan."""
    if task_id is not None:
        row = connection.execute('SELECT project_id FROM eppm.project_task WHERE id=%s', (task_id,)).fetchone()
        if row is None:
            return
        project_id = row[0]
    if project_id is not None and not connection.execute(
            "SELECT %s=ANY(eppm.permission_projects('project.edit'))", (project_id,)).fetchone()[0]:
        raise AccessDenied()
    if connection.execute('SELECT 1 FROM eppm.project_plan WHERE project_id=%s AND is_current', (project_id,)).fetchone():
        raise ValueError('This project uses versioned plans. Open Project plans, edit an alternative and save a new plan.')
