"""Compatibility entry points for the injected collaboration screens."""

from app.domain.projects.collaboration import CatalogKind
from app.main import create_collaboration_service
from app.presentation.pages import collaboration


def render_project_catalog(db_path: str | None, kind: CatalogKind) -> None:
    """Compose the catalog screen for callers using the historical DB path API."""
    collaboration.render_project_catalog(create_collaboration_service(db_path), kind)


def render_project_contacts(project_id: int, db_path: str | None) -> None:
    """Compose the contact screen for the historical project-and-path API."""
    collaboration.render_project_contacts(project_id, create_collaboration_service(db_path))


def render_project_log(project_id: int, db_path: str | None) -> None:
    """Compose the log screen for the historical project-and-path API."""
    collaboration.render_project_log(project_id, create_collaboration_service(db_path))
