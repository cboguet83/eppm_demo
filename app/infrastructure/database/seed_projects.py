"""Validated project insertion shared by infrastructure demo-data installers."""

import sqlite3

from app.application.services.projects import create_in_transaction
from app.domain.projects.project import Project
from app.domain.projects.project_types import PropertyValue
from app.infrastructure.repositories.projects import SqliteProjectStore


def create_seed_project(
    connection: sqlite3.Connection,
    *,
    project_id: int | None = None,
    name: str = "",
    status: str = "Draft",
    planned_budget: float = 0.0,
    actual_budget: float = 0.0,
    dynamic_attributes: dict[str, PropertyValue] | None = None,
    function_id: int | None = None,
    project_type_id: int | None = None,
) -> int:
    """Apply the same project validation as interactive creation on a seed transaction."""
    store = SqliteProjectStore(connection)
    type_id = store.default_type_id() if project_type_id is None else project_type_id
    return create_in_transaction(
        store,
        Project(
            project_id,
            name,
            status,
            planned_budget,
            actual_budget,
            dynamic_attributes or {},
            function_id,
            type_id,
        ),
    )
