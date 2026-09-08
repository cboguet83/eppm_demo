"""Composition root for application dependencies and Streamlit startup."""

from typing import TYPE_CHECKING

from app.application.services.organization import OrganizationService
from app.application.services.portfolio import PortfolioService
from app.application.services.projects import ProjectService
from app.application.services.project_types import ProjectTypeService
from app.application.services.schema import SchemaService

if TYPE_CHECKING:
    from app.presentation.components.project_workspace import ProjectWorkspace


def create_organization_service(db_path: str | None = None) -> OrganizationService:
    """Connect organization use cases to the existing SQLite database."""
    from app.infrastructure.repositories.organization import SqliteOrganizationGateway

    return OrganizationService(SqliteOrganizationGateway(db_path))


def create_project_type_service(db_path: str | None = None) -> ProjectTypeService:
    """Connect project-type use cases to the SQLite persistence adapter.

    Args:
        db_path: Database used by the calling screen; None uses configured settings.

    Returns:
        A service ready for use without opening a database at construction.
    """
    from app.infrastructure.repositories.project_types import SqliteProjectTypeGateway

    return ProjectTypeService(SqliteProjectTypeGateway(db_path))


def create_schema_service(db_path: str | None = None) -> SchemaService:
    """Connect schema administration to the transactional SQLite adapter."""
    from app.infrastructure.repositories.schema import SqliteSchemaGateway

    return SchemaService(SqliteSchemaGateway(db_path))


def create_project_service(db_path: str | None = None) -> ProjectService:
    """Connect transactional project use cases to the SQLite adapter."""
    from app.infrastructure.repositories.projects import SqliteProjectGateway

    return ProjectService(SqliteProjectGateway(db_path))


def create_portfolio_service(
    db_path: str | None = None, *, include_allocations: bool = True,
) -> PortfolioService:
    """Connect bounded queries and the transitional planning-capacity reader."""
    from functools import partial
    from app.infrastructure.repositories.portfolio import SqlitePortfolioReader

    allocations = None
    if include_allocations:
        from src.services.project_overallocation import overallocated_project_ids

        allocations = partial(overallocated_project_ids, db_path)
    return PortfolioService(SqlitePortfolioReader(db_path), allocations)


def create_project_workspace(db_path: str | None = None) -> ProjectWorkspace:
    """Assemble project screens and the remaining collaboration-section bridge."""
    from functools import partial
    from app.presentation.components.project_workspace import ProjectWorkspace
    from src.views.project_collaboration_view import render_project_contacts, render_project_log

    return ProjectWorkspace(
        create_project_service(db_path), create_project_type_service(db_path),
        create_portfolio_service(db_path),
        partial(render_project_contacts, db_path=db_path),
        partial(render_project_log, db_path=db_path),
    )


def main() -> None:
    """Run the transitional UI shell with the existing CLI and seeding behavior."""
    import runpy

    runpy.run_module("app.presentation.legacy_shell", run_name="__main__")


if __name__ == "__main__":
    main()
