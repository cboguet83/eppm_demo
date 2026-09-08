"""Composition root for application dependencies and Streamlit startup."""

from datetime import date
from functools import cache
from typing import TYPE_CHECKING

from app.application.services.organization import OrganizationService
from app.application.services.pool_capacity import PoolCapacityService
from app.application.services.portfolio import PortfolioService
from app.application.services.projects import ProjectService
from app.application.services.project_types import ProjectTypeService
from app.application.services.resource_pools import ResourcePoolService
from app.application.services.schema import SchemaService
from app.application.services.tags import TagService
from app.application.services.planning import PlanningService
from app.application.services.project_overallocation import ProjectOverallocationService

if TYPE_CHECKING:
    from app.infrastructure.database.pool_capacity_cache import (
        CapacityCacheState, SqliteCapacityCache,
    )
    from app.presentation.components.project_workspace import ProjectWorkspace
    from app.presentation.components.planning_workspace import PlanningWorkspace


@cache
def capacity_cache_state() -> CapacityCacheState:
    """Own one bounded process cache; storage adapters receive it explicitly."""
    from app.infrastructure.database.pool_capacity_cache import CapacityCacheState

    return CapacityCacheState()


def create_pool_capacity_cache(db_path: str | None = None) -> SqliteCapacityCache:
    """Compose the derived-data cache with the process state and current day."""
    from app.infrastructure.database.pool_capacity_cache import SqliteCapacityCache

    return SqliteCapacityCache(db_path, capacity_cache_state(), date.today)


def create_pool_capacity_service(db_path: str | None = None) -> PoolCapacityService:
    """Connect capacity use cases to one-snapshot reads and revision-checked caching."""
    from app.infrastructure.repositories.pool_capacity import SqliteCapacityReader

    return PoolCapacityService(
        SqliteCapacityReader(db_path), create_pool_capacity_cache(db_path), date.today,
    )


def create_planning_service(db_path: str | None = None) -> PlanningService:
    """Connect task use cases to the existing SQLite schema."""
    from app.infrastructure.repositories.planning import SqlitePlanningGateway

    return PlanningService(SqlitePlanningGateway(db_path))


def create_tag_service(db_path: str | None = None) -> TagService:
    """Connect tag use cases to the existing SQLite schema."""
    from app.infrastructure.repositories.tags import SqliteTagGateway

    return TagService(SqliteTagGateway(db_path))


def create_resource_pool_service(db_path: str | None = None) -> ResourcePoolService:
    """Connect pool use cases to the existing SQLite adapter."""
    from app.infrastructure.repositories.resource_pools import SqliteResourcePoolGateway

    return ResourcePoolService(SqliteResourcePoolGateway(db_path))


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
    """Connect bounded portfolio queries and layered daily-overload indicators."""
    from app.infrastructure.repositories.portfolio import SqlitePortfolioReader

    allocations = None
    if include_allocations:
        allocations = create_project_overallocation_service(db_path).overallocated_project_ids
    return PortfolioService(SqlitePortfolioReader(db_path), allocations)


def create_project_overallocation_service(db_path: str | None = None) -> ProjectOverallocationService:
    """Compose page-scoped overload indicators with the shared capacity cache."""
    return ProjectOverallocationService(create_planning_service(db_path), create_pool_capacity_service(db_path))


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


def create_planning_workspace(db_path: str | None = None) -> PlanningWorkspace:
    """Compose planning screens from task, tag, capacity, and catalog use cases."""
    from app.presentation.components.planning_workspace import PlanningWorkspace

    return PlanningWorkspace(
        create_planning_service(db_path), create_tag_service(db_path),
        create_resource_pool_service(db_path), create_pool_capacity_service(db_path),
        create_organization_service(db_path), create_schema_service(db_path),
        create_project_workspace(db_path),
    )


if __name__ == "__main__":
    main()
