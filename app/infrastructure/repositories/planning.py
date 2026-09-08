"""SQLite task persistence with caller-owned transactions and typed projections."""

from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
import json
import sqlite3

from app.application.exceptions import PlanningConflictError, PlanningStorageError
from app.application.ports.planning import ExternalTask, ProjectSummary, TaskChoice, TaskRow
from app.domain.planning.records import (
    DependencyInput,
    DependencySchedule,
    ProjectBounds,
    TaskInput,
    TaskValues,
)
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.planning_summary_cache import (
    ensure_planning_indexes,
    read_project_summaries,
)
from app.shared.logging import get_logger

logger = get_logger(__name__)

_TASK_COLUMNS = """m.id, m.project_id, m.task_name, m.phase, m.start_date,
                   m.end_date, m.progress_pct, m.description, m.predecessor_id"""
_INSERT_TASK = """INSERT INTO project_task
    (project_id, task_name, phase, start_date, end_date, progress_pct, description, predecessor_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""


def _task_params(values: TaskValues) -> tuple[object, ...]:
    return (
        values["task_name"],
        values.get("phase", "General"),
        values["start_date"],
        values["end_date"],
        values.get("progress_pct", 0),
        values.get("description", ""),
        values.get("predecessor_id"),
    )


class SqlitePlanningStore:
    """Execute task queries and writes within the gateway's single connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Use the supplied transaction; do not commit or close it here."""
        self.connection = connection

    def _tasks(self, where: str = "", params: Sequence[object] = ()) -> list[TaskRow]:
        rows = self.connection.execute(
            f"""
            SELECT {_TASK_COLUMNS}, p.task_name AS predecessor_name
            FROM project_task m LEFT JOIN project_task p ON m.predecessor_id=p.id
            {where} ORDER BY m.project_id, m.start_date, m.id
        """,
            params,
        )
        return [TaskRow(**dict(row)) for row in rows]

    def get_milestones_by_project(self, project_id: int) -> list[TaskRow]:
        """Read one project's tasks with single-predecessor labels."""
        return self._tasks("WHERE m.project_id=?", (project_id,))

    def get_milestones_for_projects(self, project_ids: list[int]) -> list[TaskRow]:
        """Batch selected projects with one bound JSON parameter."""
        if not project_ids:
            return []
        return self._tasks(
            "WHERE m.project_id IN (SELECT value FROM json_each(?))", (json.dumps(project_ids),)
        )

    def get_all_milestones(self) -> list[TaskRow]:
        """Read all tasks with their parent-project labels for explicit exports."""
        rows = self.connection.execute(f"""
            SELECT {_TASK_COLUMNS}, p.name AS project_name
            FROM project_task m LEFT JOIN project p ON m.project_id=p.id
            ORDER BY m.project_id, m.start_date, m.id
        """)
        return [TaskRow(**dict(row)) for row in rows]

    def get_milestone_by_id(self, milestone_id: int) -> TaskRow | None:
        """Read a task's stored fields by identity."""
        row = self.connection.execute(
            f"SELECT {_TASK_COLUMNS} FROM project_task m WHERE m.id=?",
            (milestone_id,),
        ).fetchone()
        return TaskRow(**dict(row)) if row else None

    def search_task_choices(self, search: str = "", *, limit: int = 50) -> list[TaskChoice]:
        """Return at most 100 minimal task choices, preserving exact #ID lookup."""
        search = search.strip()
        if search.lstrip("#").isdigit():
            where, params = "WHERE t.id=?", [int(search.lstrip("#"))]
        elif search:
            where, params = (
                "WHERE instr(lower(t.task_name),lower(?))>0 " "OR instr(lower(p.name),lower(?))>0"
            ), [search, search]
        else:
            where, params = "", []
        rows = self.connection.execute(
            "SELECT t.id,t.task_name,t.project_id,p.name AS project_name FROM project_task t "
            "JOIN project p ON p.id=t.project_id " + where + " ORDER BY t.id DESC LIMIT ?",
            params + [max(1, min(100, int(limit)))],
        )
        return [TaskChoice(**dict(row)) for row in rows]

    def _dependencies(
        self,
        where: str,
        params: Sequence[object],
        *,
        task_label: bool = True,
    ) -> list[DependencySchedule]:
        label = ", s_task.task_name AS task_name" if task_label else ""
        rows = self.connection.execute(
            f"""
            SELECT d.id, d.task_id, d.predecessor_task_id, d.predecessor_project_id,
                   d.link_type, d.lag_days, p_task.task_name AS predecessor_task_name,
                   p_task.start_date AS pred_start_date, p_task.end_date AS pred_end_date,
                   p_task.project_id AS pred_task_project_id,
                   p_proj.name AS predecessor_project_name {label}
            FROM task_dependencies d JOIN project_task s_task ON d.task_id=s_task.id
            LEFT JOIN project_task p_task ON d.predecessor_task_id=p_task.id
            LEFT JOIN project p_proj ON d.predecessor_project_id=p_proj.id
            {where}
        """,
            params,
        )
        return [DependencySchedule(**dict(row)) for row in rows]

    def get_dependencies_for_project(self, project_id: int) -> list[DependencySchedule]:
        """Read a project's enriched incoming links."""
        return self._dependencies("WHERE s_task.project_id=?", (project_id,))

    def get_dependencies_for_projects(self, project_ids: list[int]) -> list[DependencySchedule]:
        """Batch incoming links without loading unrelated tasks."""
        if not project_ids:
            return []
        return self._dependencies(
            "WHERE s_task.project_id IN (SELECT value FROM json_each(?))",
            (json.dumps(project_ids),),
        )

    def get_task_dependencies(self, task_id: int) -> list[DependencySchedule]:
        """Read enriched predecessor dates for one task."""
        return self._dependencies("WHERE d.task_id=?", (task_id,), task_label=False)

    def get_project_date_bounds(self, project_id: int) -> tuple[str | None, str | None]:
        """Aggregate one project's schedule dates."""
        row = self.connection.execute(
            "SELECT MIN(start_date),MAX(end_date) FROM project_task WHERE project_id=?",
            (project_id,),
        ).fetchone()
        return (str(row[0]), str(row[1])) if row[0] and row[1] else (None, None)

    def get_all_project_date_bounds(self) -> ProjectBounds:
        """Aggregate all project dates with integer and chart-string lookup keys."""
        result: ProjectBounds = {}
        for row in self.connection.execute(
            "SELECT project_id,MIN(start_date),MAX(end_date) FROM project_task GROUP BY project_id",
        ):
            bounds = (str(row[1]) if row[1] else None, str(row[2]) if row[2] else None)
            result[int(row[0])] = result[str(row[0])] = bounds
        return result

    def get_all_external_tasks_map(
        self,
        exclude_project_ids: list[int] | None = None,
    ) -> dict[str, list[ExternalTask]]:
        """Read minimal task summaries for explicitly requested external exports."""
        result: dict[str, list[ExternalTask]] = {}
        for row in self.connection.execute(
            """
            SELECT id,project_id,task_name,start_date,end_date FROM project_task
            WHERE project_id NOT IN (SELECT value FROM json_each(?)) ORDER BY project_id,start_date
        """,
            (json.dumps(exclude_project_ids or []),),
        ):
            result.setdefault(str(row[1]), []).append(
                ExternalTask(
                    id=int(row[0]),
                    task_name=str(row[2]),
                    start_date=str(row[3]),
                    end_date=str(row[4]),
                )
            )
        return result

    def create_task(self, project_id: int, values: TaskValues) -> int:
        """Insert normalized task fields without committing the surrounding use case."""
        cursor = self.connection.execute(_INSERT_TASK, (project_id, *_task_params(values)))
        return int(cursor.lastrowid)

    def update_task(self, task_id: int, values: TaskValues) -> bool:
        """Write normalized details, returning false for a deleted task."""
        cursor = self.connection.execute(
            """
            UPDATE project_task SET task_name=?, phase=?, start_date=?, end_date=?,
                progress_pct=?, description=?, predecessor_id=? WHERE id=?
        """,
            (*_task_params(values), task_id),
        )
        return cursor.rowcount > 0

    def insert_dependency(self, task_id: int, dependency: DependencyInput) -> None:
        """Insert one application-normalized link."""
        self.connection.execute(
            """
            INSERT INTO task_dependencies
                (task_id,predecessor_task_id,predecessor_project_id,link_type,lag_days)
            VALUES (?,?,?,?,?)
        """,
            (
                task_id,
                dependency.get("predecessor_task_id"),
                dependency.get("predecessor_project_id"),
                dependency["link_type"],
                dependency["lag_days"],
            ),
        )

    def replace_dependencies(self, task_id: int, dependencies: list[DependencyInput]) -> None:
        """Replace normalized links in the caller's transaction."""
        self.connection.execute("DELETE FROM task_dependencies WHERE task_id=?", (task_id,))
        for dependency in dependencies:
            self.insert_dependency(task_id, dependency)

    def update_dates(self, milestone_id: int, start_date: str, end_date: str) -> bool:
        """Store validated drag dates."""
        cursor = self.connection.execute(
            "UPDATE project_task SET start_date=?, end_date=? WHERE id=?",
            (start_date, end_date, milestone_id),
        )
        return cursor.rowcount > 0

    def update_progress(self, milestone_id: int, progress_pct: int) -> bool:
        """Store the progress value normalized by the domain."""
        cursor = self.connection.execute(
            "UPDATE project_task SET progress_pct=? WHERE id=?",
            (progress_pct, milestone_id),
        )
        return cursor.rowcount > 0

    def bulk_create_milestones(self, rows: list[TaskInput]) -> int:
        """Bulk insert validated import rows, preserving single-predecessor columns."""
        self.connection.executemany(
            _INSERT_TASK, [(row["project_id"], *_task_params(row)) for row in rows]
        )
        return len(rows)

    def delete_milestone(self, milestone_id: int) -> bool:
        """Clean incoming/outgoing links and legacy predecessor references atomically."""
        self.connection.execute(
            "DELETE FROM task_dependencies WHERE task_id=? OR predecessor_task_id=?",
            (milestone_id, milestone_id),
        )
        self.connection.execute(
            "UPDATE project_task SET predecessor_id=NULL WHERE predecessor_id=?",
            (milestone_id,),
        )
        cursor = self.connection.execute("DELETE FROM project_task WHERE id=?", (milestone_id,))
        return cursor.rowcount > 0

    def ensure_indexes(self) -> None:
        """Maintain the existing derived schema inside the caller's transaction."""
        ensure_planning_indexes(self.connection)

    def get_project_summaries(self, project_ids: list[int]) -> list[ProjectSummary]:
        """Read compact project headers, filling cache misses atomically."""
        return read_project_summaries(self.connection, project_ids)

    def affected_task_projects(self, task_id: int) -> tuple[set[int], set[int]]:
        """Query only the edited project's direct schedule dependents and assigned pools."""
        row = self.connection.execute(
            "SELECT project_id FROM project_task WHERE id=?", (task_id,)
        ).fetchone()
        if not row:
            return set(), set()
        project_id = row[0]
        projects = {project_id} | {
            row[0]
            for row in self.connection.execute(
                """
            SELECT DISTINCT t.project_id FROM task_dependencies d
            JOIN project_task t ON t.id=d.task_id WHERE d.predecessor_task_id=? OR d.predecessor_project_id=?
        """,
                (task_id, project_id),
            )
        }
        pools = {
            row[0]
            for row in self.connection.execute(
                "SELECT DISTINCT pool_id FROM resource_pool_assignment WHERE project_id=?",
                (project_id,),
            )
        }
        return projects, pools

    def consuming_pool_ids(self, project_ids: list[int]) -> list[int]:
        """Find positive-demand pools using a bounded project ID parameter."""
        return [
            row[0]
            for row in self.connection.execute(
                """
            SELECT DISTINCT pool_id FROM resource_pool_assignment WHERE fte_assigned>0
            AND project_id IN (SELECT value FROM json_each(?)) ORDER BY pool_id
        """,
                (json.dumps(project_ids),),
            )
        ]


class SqlitePlanningGateway:
    """Own transaction scope, connection cleanup, and safe error translation."""

    def __init__(self, db_path: str | None = None) -> None:
        """Retain configuration without opening storage."""
        self.db_path = db_path

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[SqlitePlanningStore]:
        """Reserve writes before dependent changes and close on every exit."""
        try:
            with closing(get_db(self.db_path)) as connection:
                connection.row_factory = sqlite3.Row
                with connection:
                    connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                    yield SqlitePlanningStore(connection)
        except sqlite3.IntegrityError as exc:
            raise PlanningConflictError(
                "The task change conflicts with an existing reference or constraint."
            ) from exc
        except sqlite3.DatabaseError as exc:
            logger.error("Planning storage operation failed (%s)", type(exc).__name__)
            raise PlanningStorageError(
                "Planning data could not be accessed. Please try again."
            ) from exc
