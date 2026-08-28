"""Repository for Project Master Data."""

import json
from typing import Any, Optional, Union

import pandas as pd

from src.database.connection import get_db
from src.logging_config import get_logger

logger = get_logger(__name__)


def parse_project_id(project_id: Union[int, str]) -> int:
    """Parses a project identifier into an integer.

    Args:
        project_id: Integer ID or string identifier (e.g. 1, "1", "PRJ-001").

    Returns:
        int: Normalized integer project ID.
    """
    if isinstance(project_id, int):
        return project_id
    val_str = str(project_id).strip()
    if val_str.isdigit():
        return int(val_str)
    if val_str.startswith("PRJ-"):
        part = val_str.split("-")[-1]
        if part.isdigit():
            return int(part)
    try:
        return int(val_str)
    except ValueError:
        return abs(hash(val_str)) % 1_000_000 + 1


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
                "SELECT id, name, status, planned_budget, actual_budget, dynamic_attributes FROM project ORDER BY id",
                conn,
            )

    def exists(self, project_id: Union[int, str]) -> bool:
        """Checks if a project ID already exists.

        Args:
            project_id: Project integer ID or string.

        Returns:
            bool: True if project exists.
        """
        int_id = parse_project_id(project_id)
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM project WHERE id = ?", (int_id,))
            return cursor.fetchone() is not None

    def generate_project_id(self) -> int:
        """Generates the next sequential integer project ID.

        Returns:
            int: Next sequential project ID.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM project")
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 1

    def create_project(
        self,
        project_id: Optional[Union[int, str]] = None,
        name: str = "",
        status: str = "Draft",
        planned_budget: float = 0.0,
        actual_budget: float = 0.0,
        dynamic_attributes: Optional[dict[str, Any]] = None,
    ) -> int:
        """Creates a new project record.

        Args:
            project_id: Optional explicit integer project ID (if None, autoincrements).
            name: Project title.
            status: Project status.
            planned_budget: Planned budget in USD.
            actual_budget: Actual spend in USD.
            dynamic_attributes: Dictionary of dynamic schema values.

        Returns:
            int: Inserted project ID.
        """
        dyn_dict = dynamic_attributes if dynamic_attributes is not None else {}
        dyn_json = json.dumps(dyn_dict)

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            if project_id is not None:
                int_id = parse_project_id(project_id)
                cursor.execute(
                    "INSERT INTO project (id, name, status, planned_budget, actual_budget, dynamic_attributes) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        int_id,
                        name.strip(),
                        status,
                        planned_budget,
                        actual_budget,
                        dyn_json,
                    ),
                )
                conn.commit()
                return int_id
            else:
                cursor.execute(
                    "INSERT INTO project (name, status, planned_budget, actual_budget, dynamic_attributes) VALUES (?, ?, ?, ?, ?)",
                    (
                        name.strip(),
                        status,
                        planned_budget,
                        actual_budget,
                        dyn_json,
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid or 1)

    def update_project(
        self,
        project_id: Union[int, str],
        name: str,
        status: str,
        planned_budget: float,
        actual_budget: float,
        dynamic_attributes: dict[str, Any],
    ) -> bool:
        """Updates an existing project record.

        Args:
            project_id: Unique project ID.
            name: Updated project title.
            status: Updated project status.
            planned_budget: Updated planned budget.
            actual_budget: Updated actual spend.
            dynamic_attributes: Updated dictionary of dynamic attributes.

        Returns:
            bool: True if updated.
        """
        int_id = parse_project_id(project_id)
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE project SET name = ?, status = ?, planned_budget = ?, actual_budget = ?, dynamic_attributes = ? WHERE id = ?",
                (
                    name.strip(),
                    status,
                    planned_budget,
                    actual_budget,
                    json.dumps(dynamic_attributes),
                    int_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_project(self, project_id: Union[int, str]) -> bool:
        """Deletes a project and cleans up its tasks and dependencies.

        Args:
            project_id: Project ID to delete.

        Returns:
            bool: True if deleted.
        """
        int_id = parse_project_id(project_id)
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM task_dependencies
                WHERE predecessor_project_id = ?
                   OR task_id IN (SELECT id FROM project_task WHERE project_id = ?)
                   OR predecessor_task_id IN (SELECT id FROM project_task WHERE project_id = ?)
                """,
                (int_id, int_id, int_id),
            )
            cursor.execute("UPDATE project_task SET predecessor_id = NULL WHERE project_id = ?", (int_id,))
            cursor.execute("DELETE FROM project_task WHERE project_id = ?", (int_id,))
            cursor.execute("DELETE FROM project WHERE id = ?", (int_id,))
            conn.commit()
            return cursor.rowcount > 0
