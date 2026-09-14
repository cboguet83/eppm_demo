"""PostgreSQL composition with explicit process resources and current actors."""

from __future__ import annotations

from datetime import date
from argparse import ArgumentParser
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
from app.application.services.finance import FinanceService
from app.application.services.dashboard import DashboardService

if TYPE_CHECKING:
    from app.runtime import RuntimeResources
    from app.infrastructure.postgresql.capacity_cache import PostgresCapacityCache
    from app.presentation.components.project_workspace import ProjectWorkspace
    from app.presentation.components.planning_workspace import PlanningWorkspace
    from app.presentation.components.settings_workspace import SettingsWorkspace
    from app.presentation.components.application_workspace import ApplicationWorkspace

def create_pool_capacity_cache(resources: RuntimeResources, *, access: BusinessAccess) -> PostgresCapacityCache:
    """Compose the derived-data cache with the process state and current day."""
    from app.infrastructure.postgresql.capacity_cache import PostgresCapacityCache

    return PostgresCapacityCache(resources.database, resources.key, resources.caches, date.today, access=access)


def create_pool_capacity_service(resources: RuntimeResources, *, access: BusinessAccess) -> PoolCapacityService:
    """Connect capacity use cases to one-snapshot reads and revision-checked caching."""
    from app.infrastructure.postgresql.pool_capacity import PostgresCapacityReader

    return PoolCapacityService(
        PostgresCapacityReader(resources.database, resources.key, access=access),
        create_pool_capacity_cache(resources, access=access),
        date.today,
    )


def create_planning_service(resources: RuntimeResources, *, access: BusinessAccess) -> PlanningService:
    """Connect task use cases to the native PostgreSQL schema."""
    from app.infrastructure.postgresql.planning import PostgresPlanningGateway

    return PlanningService(PostgresPlanningGateway(resources.database, resources.key, access=access, cache_state=resources.caches))


def create_tag_service(resources: RuntimeResources, *, access: BusinessAccess) -> TagService:
    """Connect tag use cases to the native PostgreSQL schema."""
    from app.infrastructure.postgresql.tags import PostgresTagGateway

    return TagService(PostgresTagGateway(resources.database, resources.key, access=access))


def create_resource_pool_service(resources: RuntimeResources, *, access: BusinessAccess) -> ResourcePoolService:
    """Connect pool use cases to the native PostgreSQL adapter."""
    from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolGateway

    return ResourcePoolService(PostgresResourcePoolGateway(resources.database, resources.key, access=access))


def create_organization_service(resources: RuntimeResources, *, access: BusinessAccess) -> OrganizationService:
    """Connect organization use cases to the native PostgreSQL database."""
    from app.infrastructure.postgresql.organization import PostgresOrganizationGateway

    return OrganizationService(PostgresOrganizationGateway(resources.database, resources.key, access=access))


def create_project_type_service(resources: RuntimeResources, *, access: BusinessAccess) -> ProjectTypeService:
    """Connect project-type use cases to the PostgreSQL persistence adapter.

    Args:
        resources: Shared process pool, signing key and bounded derived cache.

    Returns:
        A service ready for use without opening a database at construction.
    """
    from app.infrastructure.postgresql.project_types import PostgresProjectTypeGateway

    return ProjectTypeService(PostgresProjectTypeGateway(resources.database, resources.key, access=access))


def create_schema_service(resources: RuntimeResources, *, access: BusinessAccess) -> SchemaService:
    """Connect schema administration to the transactional PostgreSQL adapter."""
    from app.infrastructure.postgresql.schema import PostgresSchemaGateway

    return SchemaService(PostgresSchemaGateway(resources.database, resources.key, access=access))


def create_project_service(resources: RuntimeResources, *, access: BusinessAccess) -> ProjectService:
    """Connect transactional project use cases to the PostgreSQL adapter."""
    from app.infrastructure.postgresql.projects import PostgresProjectGateway

    return ProjectService(PostgresProjectGateway(resources.database, resources.key, access=access))


def create_portfolio_service(
    resources: RuntimeResources,
    *, access: BusinessAccess,
    include_allocations: bool = True,
) -> PortfolioService:
    """Connect bounded portfolio queries and layered daily-overload indicators."""
    from app.infrastructure.postgresql.portfolio import PostgresPortfolioReader

    allocations = None
    if include_allocations:
        allocations = create_project_overallocation_service(resources, access=access).overallocated_project_ids
    return PortfolioService(PostgresPortfolioReader(resources.database, resources.key, access=access), allocations)


def create_project_overallocation_service(
    resources: RuntimeResources,
    *,
    access: BusinessAccess,
) -> ProjectOverallocationService:
    """Compose page-scoped overload indicators with the shared capacity cache."""
    return ProjectOverallocationService(
        create_planning_service(resources, access=access), create_pool_capacity_service(resources, access=access)
    )


def create_project_workspace(resources: RuntimeResources, *, access: BusinessAccess) -> ProjectWorkspace:
    """Assemble project screens with lazily rendered collaboration sections."""
    from functools import partial
    from app.presentation.components.project_workspace import ProjectWorkspace
    from app.presentation.pages.collaboration import (
        open_project_event_dialog, render_project_contacts, render_project_log, render_project_links,
    )

    from app.presentation.pages.dashboard import render_project_budget

    collaboration = create_collaboration_service(resources, access=access)

    return ProjectWorkspace(
        create_project_service(resources, access=access),
        create_project_type_service(resources, access=access),
        create_portfolio_service(resources, access=access),
        partial(render_project_contacts, service=collaboration),
        partial(render_project_log, service=collaboration),
        create_schema_service(resources, access=access),
        partial(render_project_links, service=collaboration),
        partial(render_project_budget, service=create_dashboard_service(resources, access=access)),
        partial(open_project_event_dialog, service=collaboration),
    )


def create_collaboration_service(resources: RuntimeResources, *, access: BusinessAccess) -> CollaborationService:
    """Connect collaboration use cases to the transactional PostgreSQL adapter."""
    from app.infrastructure.postgresql.collaboration import PostgresCollaborationGateway

    return CollaborationService(PostgresCollaborationGateway(resources.database, resources.key, access=access))


def create_budget_service(resources: RuntimeResources, *, access: BusinessAccess) -> BudgetService:
    """Connect decimal budget reporting to minimal PostgreSQL projections."""
    from app.infrastructure.postgresql.budgets import PostgresBudgetReader

    return BudgetService(PostgresBudgetReader(resources.database, resources.key, access=access))


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
        help="Explicitly reseed PostgreSQL using separate operator credentials.",
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
    from app.operator_services import create_maintenance_service
    from app.shared.config import config
    from app.shared.logging import get_logger, setup_logging

    args = _startup_parser(add_help=True).parse_args()
    force, projects = bool(args.force_reseed), int(args.projects)
    if not force and projects <= 0:
        return False
    setup_logging()
    logger = get_logger(__name__)
    try:
        create_maintenance_service().startup(
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
    from app.runtime import process_runtime
    from app.shared.config.authentication import AuthenticationConfig
    from app.shared.logging import setup_logging

    setup_logging()
    try:
        settings = AuthenticationConfig.from_environment(os.environ)
        resources = process_runtime()
    except ValueError:
        st.error(t("auth.not_configured"))
        return
    authentication = create_access_service(resources, settings)
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
    render_application(create_application_workspace(resources, access=access, authentication=authentication))


def create_settings_workspace(resources: RuntimeResources, *, access: BusinessAccess) -> SettingsWorkspace:
    """Compose the lazy Settings sections from migrated application services."""
    from app.presentation.components.settings_workspace import SettingsWorkspace
    from app.application.services.wbs import WbsService
    from app.infrastructure.postgresql.projects import PostgresProjectGateway

    return SettingsWorkspace(
        create_organization_service(resources, access=access),
        create_tag_service(resources, access=access),
        create_resource_pool_service(resources, access=access),
        create_pool_capacity_service(resources, access=access),
        create_schema_service(resources, access=access),
        create_project_type_service(resources, access=access),
        create_collaboration_service(resources, access=access),
        WbsService(PostgresProjectGateway(resources.database, resources.key, access=access)),
    )


def create_application_workspace(
    resources: RuntimeResources,
    *,
    access: BusinessAccess,
    authentication: AccessService | None = None,
) -> ApplicationWorkspace:
    """Compose only authorized pages; database maintenance belongs to deployment commands."""
    from functools import partial
    from app.domain.access.models import Actor, Permission, AccessDenied
    from app.application.ports.access import AccessStore
    from app.infrastructure.postgresql.access import PostgresAccessGateway
    from app.presentation.components.application_workspace import ApplicationWorkspace
    from app.presentation.navigation import (
        PAGE_PORTFOLIO, PAGE_PLANNING, PAGE_SETTINGS, PAGE_SCHEMA_DEF, PAGE_BUDGET, PAGE_ACCESS, PAGE_FINANCE, PAGE_DASHBOARD,
    )
    from app.presentation.pages.portfolio import render_portfolio_overview
    from app.presentation.pages.planning import render_planning_milestones
    from app.presentation.pages.settings import render_settings_view
    from app.presentation.pages.budgets import render_budget_tracking
    from app.presentation.pages.access_management import render_access_management
    from app.presentation.pages.finance import render_finance
    from app.presentation.pages.dashboard import render_dashboard

    if not isinstance(access.actor, Actor):
        raise AccessDenied()

    def visibility(store: AccessStore) -> tuple[bool, bool, bool]:
        access.policy.session(store, access.actor)
        try:
            access.projects(store)
            read = True
        except AccessDenied:
            read = False
        return (read, access.global_permission(store, Permission.SHARED),
                access.global_permission(store, Permission.ACCESS))

    gateway = PostgresAccessGateway(resources.database, resources.key, access.policy)
    read, shared, administration = gateway.run(visibility, actor=access.actor)
    pages = {PAGE_DASHBOARD: partial(render_dashboard, create_dashboard_service(resources, access=access))}
    pages[PAGE_FINANCE] = partial(render_finance, create_finance_service(resources, access=access))
    totals = None
    if read:
        pages[PAGE_PORTFOLIO] = partial(render_portfolio_overview, create_project_workspace(resources, access=access))
        pages[PAGE_PLANNING] = partial(render_planning_milestones, create_planning_workspace(resources, access=access))
        pages[PAGE_BUDGET] = partial(render_budget_tracking, create_budget_service(resources, access=access))
        totals = create_planning_service(resources, access=access).get_totals
    if shared:
        settings = partial(render_settings_view, create_settings_workspace(resources, access=access))
        pages[PAGE_SETTINGS] = settings
        pages[PAGE_SCHEMA_DEF] = settings
    if administration and authentication is not None and isinstance(access.actor, Actor):
        pages[PAGE_ACCESS] = partial(render_access_management, authentication, access.actor)
    return ApplicationWorkspace(resources.identity, pages, totals)


def create_dashboard_service(resources: RuntimeResources, *, access: BusinessAccess) -> DashboardService:
    """Compose authorized dashboard and project WBS budget reporting."""
    from app.infrastructure.postgresql.dashboard import PostgresDashboardReader
    return DashboardService(PostgresDashboardReader(resources.database, resources.key, access=access))


def create_finance_service(resources: RuntimeResources, *, access: BusinessAccess) -> FinanceService:
    """Compose the independent shared budget plan with explicit actor authorization."""
    from app.infrastructure.postgresql.finance import PostgresFinanceGateway
    return FinanceService(PostgresFinanceGateway(resources.database, resources.key, access=access))


def create_planning_workspace(resources: RuntimeResources, *, access: BusinessAccess) -> PlanningWorkspace:
    """Compose planning screens from task, tag, capacity, and catalog use cases."""
    from app.presentation.components.planning_workspace import PlanningWorkspace
    from app.infrastructure.postgresql.planning_sources import PostgresPlanningSources

    return PlanningWorkspace(
        create_planning_service(resources, access=access),
        create_tag_service(resources, access=access),
        create_resource_pool_service(resources, access=access),
        create_pool_capacity_service(resources, access=access),
        create_organization_service(resources, access=access),
        create_schema_service(resources, access=access),
        create_project_workspace(resources, access=access),
        PostgresPlanningSources(resources.database, resources.key, access=access),
    )


if __name__ == "__main__":
    main()
