"""Repository for Project Master Data."""

from typing import Any, Optional, Union

import pandas as pd

from src.database.connection import get_db
from src.database.property_store import read_values, write_value, prepare_values, effective_template
from src.logging_config import get_logger
from src.models.project import Project

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
        """Load projects and active custom values in bulk."""
        with get_db(self.db_path) as conn:
            projects = pd.read_sql("SELECT p.*, t.name AS project_type FROM project p JOIN project_type t ON t.id=p.project_type_id ORDER BY p.id", conn)
            values = read_values(conn)
            applicability = {}
            for type_id in projects.get("project_type_id", []):
                if type_id not in applicability:
                    applicability[type_id] = {p["param_id"] for p in effective_template(conn, int(type_id))}
            projects["dynamic_attributes"] = [
                {pid: value for pid, value in values.get(int(row.id), {}).items() if pid in applicability[row.project_type_id]}
                for row in projects.itertuples()
            ]
            return projects

    def get_project_by_id(self, project_id: Union[int, str]) -> Optional[Project]:
        """Load all stored values, including inactive values for type restoration."""
        with get_db(self.db_path) as conn:
            cursor = conn.execute("SELECT id, name, status, planned_budget, actual_budget, function_id, project_type_id FROM project WHERE id=?", (parse_project_id(project_id),))
            row = cursor.fetchone()
            if row is None:
                return None
            return Project(id=row[0], name=row[1], status=row[2], planned_budget=row[3] or 0.0,
                           actual_budget=row[4] or 0.0, function_id=row[5], project_type_id=row[6],
                           dynamic_attributes=read_values(conn, owner_id=row[0]).get(row[0], {}))

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
            cursor.execute("SELECT MAX(COALESCE((SELECT MAX(id) FROM project),0), COALESCE((SELECT seq FROM sqlite_sequence WHERE name='project'),0))+1")
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 1

    def create_project(
        self, project_id: Optional[Union[int, str]] = None, name: str = "", status: str = "Draft",
        planned_budget: float = 0.0, actual_budget: float = 0.0,
        dynamic_attributes: Optional[dict[str, Any]] = None, function_id: Optional[int] = None,
        project_type_id: Optional[int] = None,
    ) -> int:
        with get_db(self.db_path) as conn:
            return self.create_on_connection(conn, project_id=project_id, name=name, status=status,
                planned_budget=planned_budget, actual_budget=actual_budget, dynamic_attributes=dynamic_attributes,
                function_id=function_id, project_type_id=project_type_id)

    @staticmethod
    def create_on_connection(conn, *, project_id=None, name="", status="Draft", planned_budget=0.0,
                             actual_budget=0.0, dynamic_attributes=None, function_id=None, project_type_id=None) -> int:
        """Shared transactional writer for interactive creation and both seeders."""
        if not name.strip():
            raise ValueError("Project name is required")
        if project_type_id is None:
            project_type_id = conn.execute("SELECT id FROM project_type WHERE is_general=1").fetchone()[0]
        values = prepare_values(conn, project_type_id, dynamic_attributes or {}, creating=True)
        pid = parse_project_id(project_id) if project_id is not None else None
        cursor = conn.execute("INSERT INTO project(id,name,status,planned_budget,actual_budget,function_id,project_type_id) VALUES (?,?,?,?,?,?,?)",
                             (pid, name.strip(), status, planned_budget, actual_budget, function_id, project_type_id))
        pid = int(cursor.lastrowid)
        for key, value in values.items():
            write_value(conn, pid, key, value)
        return pid

    def update_project(self, project_id: Union[int, str], name: str, status: str, planned_budget: float,
                       actual_budget: float, dynamic_attributes: dict[str, Any], function_id: Optional[int] = None,
                       project_type_id: Optional[int] = None) -> bool:
        pid = parse_project_id(project_id)
        with get_db(self.db_path) as conn:
            row = conn.execute("SELECT project_type_id FROM project WHERE id=?", (pid,)).fetchone()
            if not row:
                return False
            if not name.strip():
                raise ValueError("Project name is required")
            type_id = row[0] if project_type_id is None else project_type_id
            existing = read_values(conn, owner_id=pid).get(pid, {})
            values = prepare_values(conn, type_id, dynamic_attributes, creating=False, existing=existing)
            conn.execute("UPDATE project SET name=?,status=?,planned_budget=?,actual_budget=?,function_id=?,project_type_id=? WHERE id=?",
                         (name.strip(), status, planned_budget, actual_budget, function_id, type_id, pid))
            for key, value in values.items():
                write_value(conn, pid, key, value)
            return True

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
