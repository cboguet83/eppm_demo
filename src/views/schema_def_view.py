"""Compatibility entry point for schema administration in legacy settings."""

from app.main import create_project_type_service, create_schema_service
from app.presentation.pages.schema import render_schema_definition as _render
from src.repositories.schema_repo import SchemaRepository


def render_schema_definition(schema_repo: SchemaRepository) -> None:
    """Compose the migrated editor for the existing database-scoped settings tab."""
    _render(create_schema_service(schema_repo.db_path), create_project_type_service(schema_repo.db_path))
