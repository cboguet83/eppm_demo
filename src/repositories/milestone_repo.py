"""Repository for Project Steps, Tasks, and Schedules."""

from typing import Any, Optional, Union

import pandas as pd

from src.database.connection import get_db
from src.logging_config import get_logger
from src.repositories.project_repo import parse_project_id

logger = get_logger(__name__)


class MilestoneRepository:
    """Encapsulates all database operations for project steps and tasks."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initializes the MilestoneRepository with an optional database path.

        Args:
            db_path: Path to SQLite database. If None, uses configured default.
        """
        self.db_path = db_path

    def get_milestones_by_project(self, project_id: Union[int, str]) -> pd.DataFrame:
        """Loads all steps/tasks for a specific project sorted by start date.

        Args:
            project_id: Project integer ID or string.

        Returns:
            pd.DataFrame: DataFrame of milestone/task records.
        """
        int_id = parse_project_id(project_id)
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT m.id, m.project_id, m.task_name, m.phase, m.start_date, m.end_date, 
                       m.progress_pct, m.description, m.predecessor_id, p.task_name AS predecessor_name
                FROM project_task m
                LEFT JOIN project_task p ON m.predecessor_id = p.id
                WHERE m.project_id = ?
                ORDER BY m.start_date, m.id
                """,
                conn,
                params=(int_id,),
            )

    def get_all_milestones(self) -> pd.DataFrame:
        """Loads all steps/tasks across all projects enriched with project names.

        Returns:
            pd.DataFrame: DataFrame containing id, project_id, task_name, phase, start_date,
                end_date, progress_pct, description, predecessor_id, and project_name.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT m.id, m.project_id, m.task_name, m.phase, m.start_date, m.end_date,
                       m.progress_pct, m.description, m.predecessor_id, p.name AS project_name
                FROM project_task m
                LEFT JOIN project p ON m.project_id = p.id
                ORDER BY m.project_id, m.start_date, m.id
                """,
                conn,
            )

    def get_dependencies_for_project(self, project_id: Union[int, str]) -> list[dict[str, Any]]:
        """Retrieves all dependency records for steps in a project.

        Args:
            project_id: Project integer ID or string.

        Returns:
            list[dict[str, Any]]: List of dependency dicts.
        """
        int_id = parse_project_id(project_id)
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT d.id, d.task_id, d.predecessor_task_id, d.predecessor_project_id, 
                       d.link_type, d.lag_days,
                       p_task.task_name AS predecessor_task_name,
                       p_task.start_date AS pred_start_date,
                       p_task.end_date AS pred_end_date,
                       p_task.project_id AS pred_task_project_id,
                       p_proj.name AS predecessor_project_name,
                       s_task.task_name AS task_name
                FROM task_dependencies d
                JOIN project_task s_task ON d.task_id = s_task.id
                LEFT JOIN project_task p_task ON d.predecessor_task_id = p_task.id
                LEFT JOIN project p_proj ON d.predecessor_project_id = p_proj.id
                WHERE s_task.project_id = ?
                """,
                (int_id,),
            )
            cols = [col[0] for col in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def get_task_dependencies(self, task_id: int) -> list[dict[str, Any]]:
        """Retrieves all predecessor dependencies for a specific task.

        Args:
            task_id: Milestone/task primary key ID.

        Returns:
            list[dict[str, Any]]: List of dependency dictionaries.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT d.id, d.task_id, d.predecessor_task_id, d.predecessor_project_id, 
                       d.link_type, d.lag_days,
                       p_task.task_name AS predecessor_task_name,
                       p_task.start_date AS pred_start_date,
                       p_task.end_date AS pred_end_date,
                       p_task.project_id AS pred_task_project_id,
                       p_proj.name AS predecessor_project_name
                FROM task_dependencies d
                LEFT JOIN project_task p_task ON d.predecessor_task_id = p_task.id
                LEFT JOIN project p_proj ON d.predecessor_project_id = p_proj.id
                WHERE d.task_id = ?
                """,
                (task_id,),
            )
            cols = [col[0] for col in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def save_task_dependencies(self, task_id: int, dependencies: list[dict[str, Any]]) -> None:
        """Replaces all dependencies for a task with a new set of dependencies.

        Args:
            task_id: Milestone/task primary key ID.
            dependencies: List of dependency dicts with keys [predecessor_task_id, predecessor_project_id, link_type, lag_days].
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM task_dependencies WHERE task_id = ?", (task_id,))
            for dep in dependencies:
                p_task = dep.get("predecessor_task_id")
                if p_task is not None:
                    try:
                        p_task = int(p_task)
                        if p_task == task_id:
                            continue  # Cannot be predecessor of itself
                    except (ValueError, TypeError):
                        p_task = None

                p_proj_raw = dep.get("predecessor_project_id")
                p_proj = parse_project_id(p_proj_raw) if p_proj_raw is not None and str(p_proj_raw).strip() != "" else None
                l_type = str(dep.get("link_type", "FS")).upper().strip()
                if l_type not in ("FS", "FF", "SS", "SF"):
                    l_type = "FS"
                try:
                    lag = int(dep.get("lag_days", 0))
                except (ValueError, TypeError):
                    lag = 0

                if p_task is not None or p_proj is not None:
                    cursor.execute(
                        """
                        INSERT INTO task_dependencies 
                        (task_id, predecessor_task_id, predecessor_project_id, link_type, lag_days)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (task_id, p_task, p_proj, l_type, lag),
                    )
            conn.commit()

    def add_dependency(
        self,
        task_id: int,
        predecessor_task_id: Optional[int] = None,
        predecessor_project_id: Optional[Union[int, str]] = None,
        link_type: str = "FS",
        lag_days: int = 0,
    ) -> None:
        """Adds a single dependency for a milestone/task.

        Args:
            task_id: Successor task ID.
            predecessor_task_id: Predecessor task ID (internal or cross-project).
            predecessor_project_id: Predecessor project ID (for project-level dependencies).
            link_type: Dependency link type (FS, FF, SS, SF).
            lag_days: Offset in calendar days.
        """
        p_task = None
        if predecessor_task_id is not None:
            try:
                p_task = int(predecessor_task_id)
                if p_task == task_id:
                    return
            except (ValueError, TypeError):
                p_task = None

        p_proj = parse_project_id(predecessor_project_id) if predecessor_project_id is not None and str(predecessor_project_id).strip() != "" else None
        l_type = str(link_type).upper().strip()
        if l_type not in ("FS", "FF", "SS", "SF"):
            l_type = "FS"
        try:
            lag = int(lag_days)
        except (ValueError, TypeError):
            lag = 0

        if p_task is not None or p_proj is not None:
            with get_db(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO task_dependencies 
                    (task_id, predecessor_task_id, predecessor_project_id, link_type, lag_days)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (task_id, p_task, p_proj, l_type, lag),
                )
                conn.commit()

    def get_project_date_bounds(self, project_id: Union[int, str]) -> tuple[Optional[str], Optional[str]]:
        """Calculates the overall earliest start date and latest end date of a project.

        Args:
            project_id: Project integer ID or string.

        Returns:
            tuple[Optional[str], Optional[str]]: (min_start_date, max_end_date).
        """
        int_id = parse_project_id(project_id)
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT MIN(start_date), MAX(end_date) FROM project_task WHERE project_id = ?",
                (int_id,),
            )
            row = cursor.fetchone()
            if row and row[0] and row[1]:
                return str(row[0]), str(row[1])
            return None, None

    def get_all_project_date_bounds(self) -> dict[Any, tuple[Optional[str], Optional[str]]]:
        """Calculates earliest start and latest end dates for all projects in one query.

        Returns:
            dict[Any, tuple[Optional[str], Optional[str]]]: Map of project_id (both int and str) to (min_start, max_end).
        """
        bounds: dict[Any, tuple[Optional[str], Optional[str]]] = {}
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT project_id, MIN(start_date), MAX(end_date) FROM project_task GROUP BY project_id"
            )
            for row in cursor.fetchall():
                s_val = str(row[1]) if row[1] else None
                e_val = str(row[2]) if row[2] else None
                p_str = str(row[0])
                bounds[p_str] = (s_val, e_val)
                try:
                    bounds[int(p_str)] = (s_val, e_val)
                except (ValueError, TypeError):
                    pass
        return bounds

    def get_all_external_tasks_map(self) -> dict[str, list[dict[str, Any]]]:
        """Retrieves all tasks grouped by project ID for external link mapping in one query.

        Returns:
            dict[str, list[dict[str, Any]]]: Map of project_id string to list of step summaries.
        """
        ext_map: dict[str, list[dict[str, Any]]] = {}
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, project_id, task_name, start_date, end_date FROM project_task ORDER BY project_id, start_date"
            )
            for row in cursor.fetchall():
                p_id = str(row[1])
                if p_id not in ext_map:
                    ext_map[p_id] = []
                ext_map[p_id].append({
                    "id": int(row[0]),
                    "task_name": str(row[2]),
                    "start_date": str(row[3]),
                    "end_date": str(row[4]),
                })
        return ext_map

    def get_milestones_for_projects(self, project_ids: list[Union[int, str]]) -> pd.DataFrame:
        """Loads all steps/tasks for multiple projects sorted by project and start date.

        Args:
            project_ids: List of project IDs.

        Returns:
            pd.DataFrame: DataFrame of task/milestone records.
        """
        if not project_ids:
            return pd.DataFrame()

        int_ids = [parse_project_id(p) for p in project_ids]
        placeholders = ",".join(["?"] * len(int_ids))
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                f"""
                SELECT m.id, m.project_id, m.task_name, m.phase, m.start_date, m.end_date, 
                       m.progress_pct, m.description, m.predecessor_id, p.task_name AS predecessor_name
                FROM project_task m
                LEFT JOIN project_task p ON m.predecessor_id = p.id
                WHERE m.project_id IN ({placeholders})
                ORDER BY m.project_id, m.start_date, m.id
                """,
                conn,
                params=int_ids,
            )

    def get_dependencies_for_projects(self, project_ids: list[Union[int, str]]) -> list[dict[str, Any]]:
        """Retrieves all dependency records for steps in a list of projects in a single query.

        Args:
            project_ids: List of project IDs.

        Returns:
            list[dict[str, Any]]: List of dependency dicts.
        """
        if not project_ids:
            return []

        int_ids = [parse_project_id(p) for p in project_ids]
        placeholders = ",".join(["?"] * len(int_ids))
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT d.id, d.task_id, d.predecessor_task_id, d.predecessor_project_id, 
                       d.link_type, d.lag_days,
                       p_task.task_name AS predecessor_task_name,
                       p_task.start_date AS pred_start_date,
                       p_task.end_date AS pred_end_date,
                       p_task.project_id AS pred_task_project_id,
                       p_proj.name AS predecessor_project_name,
                       s_task.task_name AS task_name
                FROM task_dependencies d
                JOIN project_task s_task ON d.task_id = s_task.id
                LEFT JOIN project_task p_task ON d.predecessor_task_id = p_task.id
                LEFT JOIN project p_proj ON d.predecessor_project_id = p_proj.id
                WHERE s_task.project_id IN ({placeholders})
                """,
                int_ids,
            )
            cols = [col[0] for col in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def create_milestone(
        self,
        project_id: Union[int, str],
        task_name: str,
        phase: str,
        start_date: str,
        end_date: str,
        progress_pct: int,
        predecessor_id: Optional[int] = None,
        dependencies: Optional[list[dict[str, Any]]] = None,
        description: Optional[str] = None,
    ) -> int:
        """Creates a single project step or task.

        Args:
            project_id: Parent project ID.
            task_name: Task or deliverable label.
            phase: Phase category name.
            start_date: ISO date string.
            end_date: ISO date string.
            progress_pct: Completion percentage.
            predecessor_id: Optional legacy single predecessor milestone ID.
            dependencies: Optional list of dependency dictionaries.
            description: Optional detailed step description.

        Returns:
            int: Newly created step ID.
        """
        int_pid = parse_project_id(project_id)
        clean_desc = description.strip() if description else ""

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO project_task 
                (project_id, task_name, phase, start_date, end_date, progress_pct, description, predecessor_id) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int_pid,
                    task_name.strip(),
                    phase.strip() if phase.strip() else "General",
                    start_date.strip(),
                    end_date.strip(),
                    progress_pct,
                    clean_desc,
                    predecessor_id,
                ),
            )
            conn.commit()
            new_id = cursor.lastrowid or 0

        if dependencies is not None:
            self.save_task_dependencies(new_id, dependencies)
        elif predecessor_id is not None:
            self.save_task_dependencies(
                new_id,
                [{"predecessor_task_id": predecessor_id, "link_type": "FS", "lag_days": 0}],
            )

        return new_id

    def update_milestone(
        self,
        milestone_id: int,
        task_name: str,
        phase: str,
        start_date: str,
        end_date: str,
        progress_pct: int,
        predecessor_id: Optional[int] = None,
        dependencies: Optional[list[dict[str, Any]]] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Updates an existing project step or task.

        Args:
            milestone_id: ID of the step to update.
            task_name: Updated task label.
            phase: Updated phase category name.
            start_date: Updated ISO start date.
            end_date: Updated ISO end date.
            progress_pct: Updated progress percentage.
            predecessor_id: Optional legacy single predecessor milestone ID.
            dependencies: Optional list of dependency dictionaries.
            description: Optional detailed step description.

        Returns:
            bool: True if row was updated.
        """
        clean_pred = predecessor_id if predecessor_id != milestone_id else None
        clean_desc = description.strip() if description is not None else ""

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE project_task 
                SET task_name = ?, phase = ?, start_date = ?, end_date = ?, progress_pct = ?, description = ?, predecessor_id = ?
                WHERE id = ?
                """,
                (
                    task_name.strip(),
                    phase.strip() if phase.strip() else "General",
                    start_date.strip(),
                    end_date.strip(),
                    progress_pct,
                    clean_desc,
                    clean_pred,
                    milestone_id,
                ),
            )
            conn.commit()
            updated = cursor.rowcount > 0

        if dependencies is not None:
            self.save_task_dependencies(milestone_id, dependencies)
        elif predecessor_id is not None:
            self.save_task_dependencies(
                milestone_id,
                [{"predecessor_task_id": predecessor_id, "link_type": "FS", "lag_days": 0}],
            )

        return updated

    def update_dates(self, milestone_id: int, start_date: str, end_date: str) -> bool:
        """Updates only the start and end dates of a step.

        Args:
            milestone_id: Step ID.
            start_date: ISO start date string.
            end_date: ISO end date string.

        Returns:
            bool: True if updated.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE project_task SET start_date = ?, end_date = ? WHERE id = ?",
                (start_date.strip(), end_date.strip(), milestone_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_progress(self, milestone_id: int, progress_pct: int) -> bool:
        """Updates only the progress percentage of a step.

        Args:
            milestone_id: Step ID.
            progress_pct: Progress integer 0-100.

        Returns:
            bool: True if updated.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE project_task SET progress_pct = ? WHERE id = ?",
                (max(0, min(100, progress_pct)), milestone_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def bulk_create_milestones(self, rows: list[dict[str, Any]]) -> int:
        """Bulk inserts step/task records in a single database transaction.

        Args:
            rows: List of dictionary records with keys [project_id, task_name, phase, start_date, end_date, progress_pct, description, predecessor_id].

        Returns:
            int: Number of successfully inserted records.
        """
        if not rows:
            return 0

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            params_list = [
                (
                    parse_project_id(r["project_id"]),
                    r["task_name"],
                    r.get("phase", "General"),
                    r["start_date"],
                    r["end_date"],
                    int(r.get("progress_pct", 0)),
                    str(r.get("description", "")),
                    r.get("predecessor_id"),
                )
                for r in rows
            ]
            cursor.executemany(
                """
                INSERT INTO project_task 
                (project_id, task_name, phase, start_date, end_date, progress_pct, description, predecessor_id) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params_list,
            )
            conn.commit()
            return len(rows)

    def delete_milestone(self, milestone_id: int) -> bool:
        """Deletes a step/task by ID, cleaning up any task dependencies first.

        Args:
            milestone_id: Task primary key ID.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM task_dependencies WHERE task_id = ? OR predecessor_task_id = ?",
                (milestone_id, milestone_id),
            )
            cursor.execute("UPDATE project_task SET predecessor_id = NULL WHERE predecessor_id = ?", (milestone_id,))
            cursor.execute("DELETE FROM project_task WHERE id = ?", (milestone_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_milestone_by_id(self, milestone_id: int) -> Optional[dict[str, Any]]:
        """Retrieves a single project task by primary key ID.

        Args:
            milestone_id: Primary key task ID.

        Returns:
            Optional[dict[str, Any]]: Task dictionary or None if not found.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, project_id, task_name, phase, start_date, end_date, progress_pct, description, predecessor_id
                FROM project_task
                WHERE id = ?
                """,
                (milestone_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            cols = [col[0] for col in cursor.description]
            return dict(zip(cols, row))
