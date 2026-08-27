"""Repository for Project Master Data."""

import json
from typing import Any, Optional

import pandas as pd

from src.database.connection import get_db
from src.logging_config import get_logger

logger = get_logger(__name__)


class ProjectRepository:
    """Encapsulates all database operations for projects."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initializes the ProjectRepository with an optional database path.

        Args:
            db_path: Path to SQLite database. If None, uses configured default.
        """
        self.db_path = db_path

    def get_all_projects(self) -> pd.DataFrame:
        """Loads all projects.

        Returns:
            pd.DataFrame: DataFrame containing all project columns.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                "SELECT id, name, status, planned_budget, actual_budget, dynamic_attributes FROM projects ORDER BY id",
                conn,
            )

    def exists(self, project_id: str) -> bool:
        """Checks if a project ID already exists.

        Args:
            project_id: Project code.

        Returns:
            bool: True if project exists.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM projects WHERE id = ?", (project_id.strip(),))
            return cursor.fetchone() is not None

    def generate_project_id(self) -> str:
        """Generates the next sequential project ID (e.g. PRJ-001, PRJ-002).

        Returns:
            str: Next sequential project ID.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM projects")
            rows = cursor.fetchall()

            max_num = 0
            for (val,) in rows:
                if isinstance(val, str) and val.startswith("PRJ-"):
                    parts = val.split("-")
                    if len(parts) >= 2 and parts[1].isdigit():
                        try:
                            max_num = max(max_num, int(parts[1]))
                        except ValueError:
                            pass

            next_num = max_num + 1
            candidate = f"PRJ-{next_num:03d}"
            while self.exists(candidate):
                next_num += 1
                candidate = f"PRJ-{next_num:03d}"
            return candidate

    def create_project(
        self,
        project_id: str,
        name: str,
        status: str,
        planned_budget: float,
        actual_budget: float,
        dynamic_attributes: dict[str, Any],
    ) -> bool:
        """Creates a new project record.

        Args:
            project_id: Unique project code.
            name: Project title.
            status: Project status.
            planned_budget: Planned budget in USD.
            actual_budget: Actual spend in USD.
            dynamic_attributes: Dictionary of dynamic schema values.

        Returns:
            bool: True if inserted successfully.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO projects (id, name, status, planned_budget, actual_budget, dynamic_attributes) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    project_id.strip(),
                    name.strip(),
                    status,
                    planned_budget,
                    actual_budget,
                    json.dumps(dynamic_attributes),
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_project(
        self,
        project_id: str,
        name: str,
        status: str,
        planned_budget: float,
        actual_budget: float,
        dynamic_attributes: dict[str, Any],
    ) -> bool:
        """Updates an existing project record.

        Args:
            project_id: Unique project code.
            name: Updated project title.
            status: Updated project status.
            planned_budget: Updated planned budget.
            actual_budget: Updated actual spend.
            dynamic_attributes: Updated dictionary of dynamic attributes.

        Returns:
            bool: True if updated.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE projects SET name = ?, status = ?, planned_budget = ?, actual_budget = ?, dynamic_attributes = ? WHERE id = ?",
                (
                    name.strip(),
                    status,
                    planned_budget,
                    actual_budget,
                    json.dumps(dynamic_attributes),
                    project_id.strip(),
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_project(self, project_id: str) -> bool:
        """Deletes a project and cascades deletion to its milestones.

        Args:
            project_id: Project code to delete.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM projects WHERE id = ?", (project_id.strip(),))
            conn.commit()
            return cursor.rowcount > 0
