"""Composition root for application dependencies and Streamlit startup."""

from datetime import date
from argparse import ArgumentParser
from functools import cache
from typing import TYPE_CHECKING

from app.application.services.organization import OrganizationService
from app.application.services.pool_capacity import PoolCapacityService
from app.application.services.portfolio import PortfolioService
from app.application.services.business_access import BusinessAccess
from app.application.services.access import AccessService
from app.application.services.projects import ProjectService
from app.application.services.project_types import ProjectTypeService
from app.application.services.resource_pools import ResourcePoolService
from app.application.services.schema import SchemaService
from app.application.services.tags import TagService
from app.application.services.planning import PlanningService
from app.application.services.project_overallocation import ProjectOverallocationService
from app.application.services.collaboration import CollaborationService
from app.application.services.budgets import BudgetService
from app.application.services.maintenance import MaintenanceService

if TYPE_CHECKING:
    from app.infrastructure.database.pool_capacity_cache import (
        CapacityCacheState,
        SqliteCapacityCache,
    )
    from app.presentation.components.project_workspace import ProjectWorkspace
    from app.presentation.components.planning_workspace import PlanningWorkspace
    from app.presentation.components.settings_workspace import SettingsWorkspace
    from app.presentation.components.application_workspace import ApplicationWorkspace

@cache
def capacity_cache_state() -> CapacityCacheState:
    """Own one bounded process cache; storage adapters receive it explicitly."""
    from app.infrastructure.database.pool_capacity_cache import CapacityCacheState

    return CapacityCacheState()


def create_pool_capacity_cache(db_path: str | None = None, *, access: BusinessAccess) -> SqliteCapacityCache:
    """Compose the derived-data cache with the process state and current day."""
    from app.infrastructure.database.pool_capacity_cache import SqliteCapacityCache

    return SqliteCapacityCache(db_path, capacity_cache_state(), date.today, access=access)


def create_pool_capacity_service(db_path: str | None = None, *, access: BusinessAccess) -> PoolCapacityService:
    """Connect capacity use cases to one-snapshot reads and revision-checked caching."""
    from app.infrastructure.repositories.pool_capacity import SqliteCapacityReader

    return PoolCapacityService(
        SqliteCapacityReader(db_path, access=access),
        create_pool_capacity_cache(db_path, access=access),
        date.today,
    )


def create_planning_service(db_path: str | None = None, *, access: BusinessAccess) -> PlanningService:
    """Connect task use cases to the existing SQLite schema."""
    from app.infrastructure.repositories.planning import SqlitePlanningGateway

    return PlanningService(SqlitePlanningGateway(db_path, access=access))


def create_tag_service(db_path: str | None = None, *, access: BusinessAccess) -> TagService:
    """Connect tag use cases to the existing SQLite schema."""
    from app.infrastructure.repositories.tags import SqliteTagGateway

    return TagService(SqliteTagGateway(db_path, access=access))


def create_resource_pool_service(db_path: str | None = None, *, access: BusinessAccess) -> ResourcePoolService:
    """Connect pool use cases to the existing SQLite adapter."""
    from app.infrastructure.repositories.resource_pools import SqliteResourcePoolGateway

    return ResourcePoolService(SqliteResourcePoolGateway(db_path, access=access))


def create_organization_service(db_path: str | None = None, *, access: BusinessAccess) -> OrganizationService:
    """Connect organization use cases to the existing SQLite database."""
    from app.infrastructure.repositories.organization import SqliteOrganizationGateway

    return OrganizationService(SqliteOrganizationGateway(db_path, access=access))


def create_project_type_service(db_path: str | None = None, *, access: BusinessAccess) -> ProjectTypeService:
    """Connect project-type use cases to the SQLite persistence adapter.

    Args:
        db_path: Database used by the calling screen; None uses configured settings.

    Returns:
        A service ready for use without opening a database at construction.
    """
    from app.infrastructure.repositories.project_types import SqliteProjectTypeGateway

    return ProjectTypeService(SqliteProjectTypeGateway(db_path, access=access))


def create_schema_service(db_path: str | None = None, *, access: BusinessAccess) -> SchemaService:
    """Connect schema administration to the transactional SQLite adapter."""
    from app.infrastructure.repositories.schema import SqliteSchemaGateway

    return SchemaService(SqliteSchemaGateway(db_path, access=access))


def create_project_service(db_path: str | None = None, *, access: BusinessAccess) -> ProjectService:
    """Connect transactional project use cases to the SQLite adapter."""
    from app.infrastructure.repositories.projects import SqliteProjectGateway

    return ProjectService(SqliteProjectGateway(db_path, access=access))


def create_portfolio_service(
    db_path: str | None = None,
    *, access: BusinessAccess,
    include_allocations: bool = True,
) -> PortfolioService:
    """Connect bounded portfolio queries and layered daily-overload indicators."""
    from app.infrastructure.repositories.portfolio import SqlitePortfolioReader

    allocations = None
    if include_allocations:
        allocations = create_project_overallocation_service(db_path, access=access).overallocated_project_ids
    return PortfolioService(SqlitePortfolioReader(db_path, access=access), allocations)


def create_project_overallocation_service(
    db_path: str | None = None,
    *,
    access: BusinessAccess,
) -> ProjectOverallocationService:
    """Compose page-scoped overload indicators with the shared capacity cache."""
    return ProjectOverallocationService(
        create_planning_service(db_path, access=access), create_pool_capacity_service(db_path, access=access)
    )


def create_project_workspace(db_path: str | None = None, *, access: BusinessAccess) -> ProjectWorkspace:
    """Assemble project screens with lazily rendered collaboration sections."""
    from functools import partial
    from app.presentation.components.project_workspace import ProjectWorkspace
    from app.presentation.pages.collaboration import render_project_contacts, render_project_log, render_project_links

    collaboration = create_collaboration_service(db_path, access=access)

    return ProjectWorkspace(
        create_project_service(db_path, access=access),
        create_project_type_service(db_path, access=access),
        create_portfolio_service(db_path, access=access),
        partial(render_project_contacts, service=collaboration),
        partial(render_project_log, service=collaboration),
        create_schema_service(db_path, access=access),
        partial(render_project_links, service=collaboration),
    )


def create_collaboration_service(db_path: str | None = None, *, access: BusinessAccess) -> CollaborationService:
    """Connect collaboration use cases to the transactional SQLite adapter."""
    from app.infrastructure.repositories.collaboration import SqliteCollaborationGateway

    return CollaborationService(SqliteCollaborationGateway(db_path, access=access))


def create_budget_service(db_path: str | None = None, *, access: BusinessAccess) -> BudgetService:
    """Connect decimal budget reporting to minimal SQLite projections."""
    from app.infrastructure.repositories.budgets import SqliteBudgetReader

    return BudgetService(SqliteBudgetReader(db_path, access=access))


def create_maintenance_service(db_path: str | None = None) -> MaintenanceService:
    """Connect startup and explicit maintenance to SQLite infrastructure."""
    from app.infrastructure.database.maintenance import SqliteMaintenanceGateway

    return MaintenanceService(SqliteMaintenanceGateway(db_path))


def main() -> None:
    """Run a startup command or compose the Streamlit application."""
    import streamlit as st

    if not st.runtime.exists() and _run_cli():
        return
    run_app()


def parse_cli_args(argv: list[str] | None = None) -> tuple[bool, int]:
    """Parse the established startup flags while tolerating Streamlit arguments."""
    args, _ = _startup_parser().parse_known_args(argv)
    return bool(args.force_reseed), int(args.projects)


def _startup_parser(*, add_help: bool = False) -> ArgumentParser:
    """Build the command-line parser for the application entry point."""
    parser = ArgumentParser(description="PPM Studio Pro", add_help=add_help, allow_abbrev=False)
    parser.add_argument(
        "--force-reseed",
        action="store_true",
        help="Force re-seeding the database on startup.",
    )
    parser.add_argument(
        "--projects",
        type=int,
        default=0,
        help="Number of mock projects to generate when seeding.",
    )
    return parser


def _run_cli() -> bool:
    """Handle explicit help or seeding requests without rendering a bare UI."""
    from app.application.exceptions import DatabaseMaintenanceError
    from app.shared.config import config
    from app.shared.logging import get_logger, setup_logging

    args = _startup_parser(add_help=True).parse_args()
    force, projects = bool(args.force_reseed), int(args.projects)
    if not force and projects <= 0:
        return False
    setup_logging()
    logger = get_logger(__name__)
    try:
        create_maintenance_service(config.db_path).startup(
            force=True,
            projects=projects if projects > 0 else config.seed_projects_count,
        )
    except (DatabaseMaintenanceError, ValueError) as error:
        logger.error("%s", error)
        raise SystemExit(1) from None
    logger.info("Database seeding completed successfully.")
    return True


def run_app() -> None:
    """Resolve a real OIDC session before composing any business services or pages."""
    import os
    import streamlit as st
    from app.presentation.components.authentication import account_gate
    from app.presentation.shell import render_application
    from app.presentation.i18n import t
    from app.security import create_access_service
    from app.shared.config import config
    from app.shared.config.authentication import AuthenticationConfig
    from app.shared.logging import setup_logging

    setup_logging()
    try:
        settings = AuthenticationConfig.from_environment(os.environ)
    except ValueError:
        st.error(t("auth.not_configured"))
        return
    authentication = create_access_service(config.db_path, settings)
    actor = account_gate(authentication, st.context.cookies.get("eppm_session", ""))
    if actor is None:
        return
    import hmac

    current, status, revision = authentication.browser_identity(st.context.cookies.get("eppm_session", ""))
    if not hmac.compare_digest(st.context.headers.get("x-eppm-browser-session", ""),
                               settings.session_binding(current.session_hash, status, revision)):
        st.error(t("auth.invalid_transport"))
        return
    access = BusinessAccess(actor, authentication.policy)
    render_application(create_application_workspace(config.db_path, access=access, authentication=authentication))


def create_settings_workspace(db_path: str | None = None, *, access: BusinessAccess) -> SettingsWorkspace:
    """Compose the lazy Settings sections from migrated application services."""
    from app.presentation.components.settings_workspace import SettingsWorkspace

    return SettingsWorkspace(
        create_organization_service(db_path, access=access),
        create_tag_service(db_path, access=access),
        create_resource_pool_service(db_path, access=access),
        create_pool_capacity_service(db_path, access=access),
        create_schema_service(db_path, access=access),
        create_project_type_service(db_path, access=access),
        create_collaboration_service(db_path, access=access),
    )


def create_application_workspace(
    db_path: str | None = None,
    *,
    access: BusinessAccess,
    authentication: AccessService | None = None,
) -> ApplicationWorkspace:
    """Compose only authorized pages; database maintenance belongs to deployment commands."""
    from functools import partial
    from pathlib import Path
    from app.domain.access.models import Actor, Permission, AccessDenied
    from app.infrastructure.repositories.access import SqliteAccessGateway
    from app.shared.config import config
    from app.presentation.components.application_workspace import ApplicationWorkspace
    from app.presentation.navigation import (
        PAGE_PORTFOLIO, PAGE_PLANNING, PAGE_SETTINGS, PAGE_SCHEMA_DEF, PAGE_BUDGET, PAGE_ACCESS,
    )
    from app.presentation.pages.portfolio import render_portfolio_overview
    from app.presentation.pages.planning import render_planning_milestones
    from app.presentation.pages.settings import render_settings_view
    from app.presentation.pages.budgets import render_budget_tracking
    from app.presentation.pages.access_management import render_access_management

    identity = str(Path(db_path or config.db_path).resolve())
    with SqliteAccessGateway(identity).transaction() as store:
        try:
            access.projects(store)
            read = True
        except AccessDenied:
            read = False
        shared = access.global_permission(store, Permission.SHARED)
        administration = access.global_permission(store, Permission.ACCESS)
    pages = {}
    totals = None
    if read:
        pages[PAGE_PORTFOLIO] = partial(render_portfolio_overview, create_project_workspace(identity, access=access))
        pages[PAGE_PLANNING] = partial(render_planning_milestones, create_planning_workspace(identity, access=access))
        pages[PAGE_BUDGET] = partial(render_budget_tracking, create_budget_service(identity, access=access))
        totals = create_planning_service(identity, access=access).get_totals
    if shared:
        settings = partial(render_settings_view, create_settings_workspace(identity, access=access))
        pages[PAGE_SETTINGS] = settings
        pages[PAGE_SCHEMA_DEF] = settings
    if administration and authentication is not None and isinstance(access.actor, Actor):
        pages[PAGE_ACCESS] = partial(render_access_management, authentication, access.actor)
    return ApplicationWorkspace(identity, pages, totals)


def create_planning_workspace(db_path: str | None = None, *, access: BusinessAccess) -> PlanningWorkspace:
    """Compose planning screens from task, tag, capacity, and catalog use cases."""
    from app.presentation.components.planning_workspace import PlanningWorkspace

    return PlanningWorkspace(
        create_planning_service(db_path, access=access),
        create_tag_service(db_path, access=access),
        create_resource_pool_service(db_path, access=access),
        create_pool_capacity_service(db_path, access=access),
        create_organization_service(db_path, access=access),
        create_schema_service(db_path, access=access),
        create_project_workspace(db_path, access=access),
    )


if __name__ == "__main__":
    main()
