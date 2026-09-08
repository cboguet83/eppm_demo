"""Compatibility entry points for project dialogs called by legacy planning."""

from app.main import create_project_workspace
from app.presentation.components.project_dialogs import (
    _dynamic_project_value, _render_dynamic_field, _render_dynamic_fields, _save_project,
    open_create_project_dialog as _create, open_edit_project_dialog as _edit,
)
from src.repositories.project_repo import ProjectRepository
from src.repositories.schema_repo import SchemaRepository


def _manager_options(project_repo: ProjectRepository) -> tuple[list[int | None], dict[int | None, str]]:
    from app.presentation.components.project_dialogs import _manager_options as options
    return options(create_project_workspace(project_repo.db_path))


def open_create_project_dialog(project_repo: ProjectRepository, schema_repo: SchemaRepository) -> None:
    """Compose the migrated dialog for the existing single-database workspace."""
    _create(create_project_workspace(project_repo.db_path))


def open_edit_project_dialog(project_id: int, project_repo: ProjectRepository, schema_repo: SchemaRepository) -> None:
    """Keep the legacy planning/portfolio call signature."""
    _edit(project_id, create_project_workspace(project_repo.db_path))
