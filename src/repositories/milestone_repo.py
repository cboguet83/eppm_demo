"""Repository for Project Steps, Milestones, and Schedules."""

from typing import Any, Optional

import pandas as pd

from src.database.connection import get_db
from src.logging_config import get_logger

logger = get_logger(__name__)


class MilestoneRepository:
    """Encapsulates all database operations for project steps and milestones."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initializes the MilestoneRepository with an optional database path.

        Args:
            db_path: Path to SQLite database. If None, uses configured default.
        """
        self.db_path = db_path

    def get_milestones_by_project(self, project_id: str) -> pd.DataFrame:
        """Loads all steps/milestones for a specific project sorted by start date.

        Args:
            project_id: Project code.

        Returns:
            pd.DataFrame: DataFrame of milestone records.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT m.id, m.project_id, m.task_name, m.phase, m.start_date, m.end_date, 
                       m.progress_pct, m.predecessor_id, p.task_name AS predecessor_name
                FROM project_milestones m
                LEFT JOIN project_milestones p ON m.predecessor_id = p.id
                WHERE m.project_id = ?
                ORDER BY m.start_date, m.id
                """,
                conn,
                params=(project_id.strip(),),
            )

    def create_milestone(
        self,
        project_id: str,
        task_name: str,
        phase: str,
        start_date: str,
        end_date: str,
        progress_pct: int,
        predecessor_id: Optional[int] = None,
    ) -> int:
        """Creates a single project step or milestone.

        Args:
            project_id: Parent project code.
            task_name: Task or deliverable label.
            phase: Phase category name.
            start_date: ISO date string.
            end_date: ISO date string.
            progress_pct: Completion percentage.
            predecessor_id: Optional predecessor milestone ID.

        Returns:
            int: Newly created milestone ID.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO project_milestones 
                (project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id.strip(),
                    task_name.strip(),
                    phase.strip() if phase.strip() else "General",
                    start_date.strip(),
                    end_date.strip(),
                    progress_pct,
                    predecessor_id,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def update_milestone(
        self,
        milestone_id: int,
        task_name: str,
        phase: str,
        start_date: str,
        end_date: str,
        progress_pct: int,
        predecessor_id: Optional[int] = None,
    ) -> bool:
        """Updates an existing project step or milestone.

        Args:
            milestone_id: ID of the step to update.
            task_name: Updated task label.
            phase: Updated phase category name.
            start_date: Updated ISO start date.
            end_date: Updated ISO end date.
            progress_pct: Updated progress percentage.
            predecessor_id: Optional predecessor milestone ID.

        Returns:
            bool: True if row was updated.
        """
        # A task cannot be its own predecessor
        clean_pred = predecessor_id if predecessor_id != milestone_id else None

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE project_milestones 
                SET task_name = ?, phase = ?, start_date = ?, end_date = ?, progress_pct = ?, predecessor_id = ?
                WHERE id = ?
                """,
                (
                    task_name.strip(),
                    phase.strip() if phase.strip() else "General",
                    start_date.strip(),
                    end_date.strip(),
                    progress_pct,
                    clean_pred,
                    milestone_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_dates(self, milestone_id: int, start_date: str, end_date: str) -> bool:
        """Updates only the start and end dates of a step (e.g. via drag and drop).

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
                "UPDATE project_milestones SET start_date = ?, end_date = ? WHERE id = ?",
                (start_date.strip(), end_date.strip(), milestone_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_progress(self, milestone_id: int, progress_pct: int) -> bool:
        """Updates only the progress percentage of a step.

        Args:
            milestone_id: Step ID.
            progress_pct: Percentage from 0 to 100.

        Returns:
            bool: True if updated.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE project_milestones SET progress_pct = ? WHERE id = ?",
                (max(0, min(100, progress_pct)), milestone_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def bulk_create_milestones(self, rows: list[dict[str, Any]]) -> int:
        """Bulk inserts step/milestone records in a single database transaction.

        Args:
            rows: List of dictionary records with keys [project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id].

        Returns:
            int: Number of successfully inserted records.
        """
        if not rows:
            return 0

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            params_list = [
                (
                    r["project_id"],
                    r["task_name"],
                    r.get("phase", "General"),
                    r["start_date"],
                    r["end_date"],
                    int(r.get("progress_pct", 0)),
                    r.get("predecessor_id"),
                )
                for r in rows
            ]
            cursor.executemany(
                """
                INSERT INTO project_milestones 
                (project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                params_list,
            )
            conn.commit()
            return len(rows)

    def delete_milestone(self, milestone_id: int) -> bool:
        """Deletes a step/milestone by ID.

        Args:
            milestone_id: Milestone primary key ID.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM project_milestones WHERE id = ?", (milestone_id,))
            conn.commit()
            return cursor.rowcount > 0
