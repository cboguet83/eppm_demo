"""Scoped native schedule headers without loading individual tasks into Python."""

import psycopg

from app.application.ports.planning import ProjectSummary
from app.infrastructure.postgresql.project_dependencies import read_project_dependencies


def read_project_summaries(connection: psycopg.Connection, project_ids: list[int]) -> list[ProjectSummary]:
    """Aggregate current visible bounds and warnings in the caller's snapshot.

    Native date subtraction preserves the four dependency rules and avoids
    overflowing a date when a large lag is supplied. Task endpoints take
    precedence over project endpoints. RLS excludes hidden dependencies before
    they can influence flags. Revision-keyed caching is installed separately.
    """
    if not project_ids:
        return []
    summaries = [ProjectSummary(id=row[0], name=row[1], start=row[2], end=row[3], taskCount=row[4],
                           progress=float(row[5]), hasViolations=row[6]) for row in connection.execute('''
        WITH scope AS MATERIALIZED (SELECT id FROM eppm.project WHERE id=ANY(%s::bigint[])),
        selected_links AS MATERIALIZED (
            SELECT d.* FROM eppm.task_dependencies d JOIN eppm.project_task task ON task.id=d.task_id
            WHERE task.project_id IN (SELECT id FROM scope)
        ), bounds AS (
            SELECT project_id,min(start_date) AS first_date,max(end_date) AS last_date,count(*) AS task_count,
                   avg(progress_pct) AS progress FROM eppm.project_task
            WHERE project_id IN (SELECT id FROM scope UNION SELECT predecessor_project_id
                                FROM selected_links WHERE predecessor_task_id IS NULL)
            GROUP BY project_id
        ), violations AS (
            SELECT task.project_id FROM selected_links d JOIN eppm.project_task task ON task.id=d.task_id
            LEFT JOIN eppm.project_task pred ON pred.id=d.predecessor_task_id
            LEFT JOIN bounds b ON b.project_id=d.predecessor_project_id
            WHERE (CASE WHEN upper(d.link_type) IN ('FF','SF') THEN task.end_date ELSE task.start_date END)
                - (CASE WHEN d.predecessor_task_id IS NOT NULL THEN
                    CASE WHEN upper(d.link_type) IN ('SS','SF') THEN pred.start_date ELSE pred.end_date END
                   ELSE CASE WHEN upper(d.link_type) IN ('SS','SF') THEN b.first_date ELSE b.last_date END END)
                < coalesce(d.lag_days,0)
            GROUP BY task.project_id
        ) SELECT p.id,p.name,to_char(b.first_date,'YYYY-MM-DD'),to_char(b.last_date,'YYYY-MM-DD'),
                 coalesce(b.task_count,0),coalesce(b.progress,0),v.project_id IS NOT NULL
          FROM scope JOIN eppm.project p USING(id) LEFT JOIN bounds b ON b.project_id=p.id
          LEFT JOIN violations v ON v.project_id=p.id ORDER BY p.id''', (project_ids,))]
    by_id = {summary['id']: summary for summary in summaries}
    for dependency in read_project_dependencies(connection, project_ids):
        summary = by_id[dependency['project_id']]
        summary.setdefault('projectDependencies', []).append(dependency)
        summary['hasViolations'] |= dependency['is_violated']
    return summaries
