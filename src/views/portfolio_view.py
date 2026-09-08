"""Compatibility entry points for the migrated portfolio page."""

from app.main import create_project_workspace
from app.presentation.pages.portfolio import (
    ALLOWED_DYNAMIC_PARAMS, _build_portfolio_table_rows, _portfolio_table_value,
    _sync_portfolio_project_selection, _portfolio_columns,
    _load_portfolio_page, _load_portfolio_facet,
    render_portfolio_overview as _render,
    _render_project_details_panel as _details,
)
from src.repositories.project_repo import ProjectRepository
from src.repositories.schema_repo import SchemaRepository


def render_portfolio_overview(project_repo: ProjectRepository, schema_repo: SchemaRepository) -> None:
    """Compose a migrated workspace for the legacy navigation shell."""
    _render(create_project_workspace(project_repo.db_path))


def _render_project_details_panel(selected_proj, params, project_repo, schema_repo) -> None:
    """Retain the existing helper signature for integrations."""
    _details(selected_proj, params, create_project_workspace(project_repo.db_path))
