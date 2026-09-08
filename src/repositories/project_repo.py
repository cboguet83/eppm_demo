"""Compatibility facade for legacy project callers and bulk seeders."""

import sqlite3
from typing import Any, Union
import pandas as pd

from app.main import create_project_service
from app.application.services.projects import create_in_transaction
from app.domain.projects.project import Project
from app.infrastructure.repositories.projects import SqliteProjectGateway, SqliteProjectStore
from src.repositories.project_errors import legacy_project_errors


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
    """Keep historical IDs, DataFrames, and exceptions outside the migrated core."""

    def __init__(self, db_path: str | None = None) -> None:
        """Compose project use cases for the existing database path."""
        self.db_path = db_path
        self.service = create_project_service(db_path)
        self._reader = SqliteProjectGateway(db_path)

    def get_all_projects(self) -> pd.DataFrame:
        """Return the legacy bulk-export frame with active custom values."""
        with legacy_project_errors():
            rows = self._reader.read_catalog()
        return pd.DataFrame(rows, columns=["id", "name", "status", "planned_budget", "actual_budget",
                                           "function_id", "project_type_id", "project_type", "dynamic_attributes"])

    def get_planning_catalog(self, property_ids: tuple[str, ...] = ()) -> pd.DataFrame:
        """Load only the custom properties requested by planning filters."""
        with legacy_project_errors():
            rows = self._reader.read_catalog(property_ids)
        return pd.DataFrame(rows, columns=["id", "name", "status", "function_id", "project_type_id",
                                           "project_template", "dynamic_attributes"])

    def get_project_by_id(self, project_id: int | str) -> Project | None:
        """Normalize historical IDs and read the complete project record."""
        with legacy_project_errors():
            return self.service.get_project_by_id(parse_project_id(project_id))

    def exists(self, project_id: int | str) -> bool:
        """Check a legacy project ID without loading its values."""
        with legacy_project_errors():
            return self.service.exists(parse_project_id(project_id))

    def generate_project_id(self) -> int:
        """Return an ID preview that respects deleted-project sequences."""
        with legacy_project_errors():
            return self.service.generate_project_id()

    def create_project(
        self, project_id: int | str | None = None, name: str = "", status: str = "Draft",
        planned_budget: float = 0.0, actual_budget: float = 0.0,
        dynamic_attributes: dict[str, Any] | None = None, function_id: int | None = None,
        project_type_id: int | None = None,
    ) -> int:
        """Delegate creation while retaining flexible legacy property inputs."""
        with legacy_project_errors():
            return self.service.create_project(
                parse_project_id(project_id) if project_id is not None else None,
                name, status, planned_budget, actual_budget, dynamic_attributes, function_id, project_type_id,
            )

    @staticmethod
    def create_on_connection(
        conn: sqlite3.Connection, *, project_id: int | str | None = None, name: str = "",
        status: str = "Draft", planned_budget: float = 0.0, actual_budget: float = 0.0,
        dynamic_attributes: dict[str, Any] | None = None, function_id: int | None = None,
        project_type_id: int | None = None,
    ) -> int:
        """Keep a seeder's transaction and connection under its caller's control."""
        store = SqliteProjectStore(conn)
        type_id = store.default_type_id() if project_type_id is None else project_type_id
        return create_in_transaction(store, Project(
            parse_project_id(project_id) if project_id is not None else None,
            name, status, planned_budget, actual_budget, dynamic_attributes or {}, function_id, type_id,
        ))

    def update_project(
        self, project_id: int | str, name: str, status: str, planned_budget: float,
        actual_budget: float, dynamic_attributes: dict[str, Any], function_id: int | None = None,
        project_type_id: int | None = None,
    ) -> bool:
        """Delegate atomic edits while retaining the legacy calling convention."""
        with legacy_project_errors():
            return self.service.update_project(parse_project_id(project_id), name, status, planned_budget,
                                               actual_budget, dynamic_attributes, function_id, project_type_id)

    def delete_project(self, project_id: int | str) -> bool:
        """Delete project dependencies through the transactional use case."""
        with legacy_project_errors():
            return self.service.delete_project(parse_project_id(project_id))
