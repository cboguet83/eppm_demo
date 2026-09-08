"""Existing planning indexes, summary projection, and invalidation triggers."""

import json
import sqlite3

from app.application.ports.planning import ProjectSummary


def install_summary_cache(connection: sqlite3.Connection) -> None:
    """Install the existing derived table and triggers without changing their schema."""
    connection.execute("""CREATE TABLE IF NOT EXISTS planning_summary_cache (
        project_id INTEGER PRIMARY KEY REFERENCES project(id) ON DELETE CASCADE,
        name TEXT,start TEXT,end TEXT,task_count INTEGER,progress REAL,has_violations INTEGER)""")
    for table in ("project_task", "task_dependencies", "project"):
        for event in ("INSERT", "UPDATE", "DELETE"):
            refs = (
                ("OLD", "NEW")
                if event == "UPDATE"
                else ("OLD",) if event == "DELETE" else ("NEW",)
            )
            queries = []
            for ref in refs:
                if table == "project":
                    queries.append(f"SELECT {ref}.id")
                elif table == "task_dependencies":
                    queries.append(f"SELECT project_id FROM project_task WHERE id={ref}.task_id")
                else:
                    queries.append(f"SELECT {ref}.project_id")
                    queries.append(
                        f"""SELECT t.project_id FROM task_dependencies d JOIN project_task t ON t.id=d.task_id
                        WHERE d.predecessor_task_id={ref}.id OR d.predecessor_project_id={ref}.project_id"""
                    )
            connection.execute(
                f"""CREATE TRIGGER IF NOT EXISTS planning_summary_{table}_{event.lower()}
                BEFORE {event} ON {table} BEGIN DELETE FROM planning_summary_cache WHERE project_id IN
                ({' UNION '.join(queries)}); END"""
            )


def ensure_planning_indexes(connection: sqlite3.Connection) -> None:
    """Maintain indexes for both existing bind mounts and fresh databases."""
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_planning_task_project ON project_task(project_id,start_date,id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_planning_dependency_task ON task_dependencies(task_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_planning_dependency_predecessor ON task_dependencies(predecessor_task_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_planning_dependency_project ON task_dependencies(predecessor_project_id)"
    )
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name='planning_summary_cache'"
    ).fetchone():
        install_summary_cache(connection)


def read_project_summaries(
    connection: sqlite3.Connection,
    project_ids: list[int],
) -> list[ProjectSummary]:
    """Read or fill compact summaries inside the caller's reserved transaction.

    The existing SQL warning projection mirrors the four domain link rules and
    avoids hydrating all task records when opening a large portfolio schedule.
    """
    cached = {
        row[0]: row
        for row in connection.execute(
            "SELECT * FROM planning_summary_cache WHERE project_id IN (SELECT value FROM json_each(?))",
            (json.dumps(project_ids),),
        )
    }
    missing = [pid for pid in project_ids if pid not in cached]
    rows = []
    if missing:
        rows = connection.execute(
            """WITH scope AS (SELECT value id FROM json_each(?)), bounds AS (
            SELECT project_id,MIN(start_date) start,MAX(end_date) end,COUNT(*) task_count,
                   AVG(progress_pct) progress FROM project_task
            WHERE project_id IN (SELECT id FROM scope UNION SELECT d.predecessor_project_id
                FROM task_dependencies d JOIN project_task s ON s.id=d.task_id
                WHERE s.project_id IN (SELECT id FROM scope) AND d.predecessor_task_id IS NULL)
            GROUP BY project_id
        ), violations AS (
            SELECT s.project_id,COUNT(*) violations FROM task_dependencies d
            JOIN project_task s ON s.id=d.task_id
            LEFT JOIN project_task p ON p.id=d.predecessor_task_id
            LEFT JOIN bounds b ON b.project_id=d.predecessor_project_id
            WHERE s.project_id IN (SELECT id FROM scope) AND
              julianday(CASE WHEN UPPER(d.link_type) IN ('FF','SF') THEN s.end_date ELSE s.start_date END)
              < julianday(CASE WHEN d.predecessor_task_id IS NOT NULL THEN
                  CASE WHEN UPPER(d.link_type) IN ('SS','SF') THEN p.start_date ELSE p.end_date END
                ELSE CASE WHEN UPPER(d.link_type) IN ('SS','SF') THEN b.start ELSE b.end END END)
                + COALESCE(d.lag_days,0)
            GROUP BY s.project_id
        ) SELECT p.id,p.name,b.start,b.end,COALESCE(b.task_count,0),COALESCE(b.progress,0),
                 COALESCE(v.violations,0)>0
          FROM project p LEFT JOIN bounds b ON b.project_id=p.id
          LEFT JOIN violations v ON v.project_id=p.id
          WHERE p.id IN (SELECT id FROM scope) ORDER BY p.id""",
            (json.dumps(missing),),
        ).fetchall()
        connection.executemany(
            "INSERT OR REPLACE INTO planning_summary_cache VALUES(?,?,?,?,?,?,?)", rows
        )
    return [
        ProjectSummary(
            id=int(row[0]),
            name=str(row[1]),
            start=row[2],
            end=row[3],
            taskCount=int(row[4]),
            progress=float(row[5]),
            hasViolations=bool(row[6]),
        )
        for row in sorted([*cached.values(), *rows], key=lambda row: row[0])
    ]
