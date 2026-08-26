"""Repository for Project Milestones and Schedules."""

from typing import Any, Optional

import pandas as pd

from src.database.connection import get_db
from src.logging_config import get_logger

logger = get_logger(__name__)


class MilestoneRepository:
    """Encapsulates all database operations for project milestones."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initializes the MilestoneRepository with an optional database path.

        Args:
            db_path: Path to SQLite database. If None, uses configured default.
        """
        self.db_path = db_path

    def get_milestones_by_project(self, project_id: str) -> pd.DataFrame:
        """Loads all milestones for a specific project sorted by start date.

        Args:
            project_id: Project code.

        Returns:
            pd.DataFrame: DataFrame of milestone records.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                "SELECT id, project_id, task_name, phase, start_date, end_date, progress_pct FROM project_milestones WHERE project_id = ? ORDER BY start_date",
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
    ) -> int:
        """Creates a single project milestone.

        Args:
            project_id: Parent project code.
            task_name: Task or deliverable label.
            phase: Phase category name.
            start_date: ISO date string.
            end_date: ISO date string.
            progress_pct: Completion percentage.

        Returns:
            int: Newly created milestone ID.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO project_milestones (project_id, task_name, phase, start_date, end_date, progress_pct) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    project_id.strip(),
                    task_name.strip(),
                    phase.strip() if phase.strip() else "General",
                    start_date.strip(),
                    end_date.strip(),
                    progress_pct,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def bulk_create_milestones(self, rows: list[dict[str, Any]]) -> int:
        """Bulk inserts milestone records in a single database transaction.

        Args:
            rows: List of dictionary records with keys [project_id, task_name, phase, start_date, end_date, progress_pct].

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
                )
                for r in rows
            ]
            cursor.executemany(
                "INSERT INTO project_milestones (project_id, task_name, phase, start_date, end_date, progress_pct) VALUES (?, ?, ?, ?, ?, ?)",
                params_list,
            )
            conn.commit()
            return len(rows)

    def delete_milestone(self, milestone_id: int) -> bool:
        """Deletes a milestone by ID.

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
