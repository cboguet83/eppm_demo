"""Explicit composition for deployment commands and isolated fixture databases.

Running application code must import actor-required factories from app.main.
These operator entry points are never exposed through HTTP, pages, or components.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.application.services.access import AccessService
    from app.application.services.budgets import BudgetService
    from app.application.services.collaboration import CollaborationService
    from app.application.services.maintenance import MaintenanceService
    from app.application.services.organization import OrganizationService
    from app.application.services.planning import PlanningService
    from app.application.services.pool_capacity import PoolCapacityService
    from app.application.services.portfolio import PortfolioService
    from app.application.services.project_overallocation import ProjectOverallocationService
    from app.application.services.project_types import ProjectTypeService
    from app.application.services.projects import ProjectService
    from app.application.services.resource_pools import ResourcePoolService
    from app.application.services.schema import SchemaService
    from app.application.services.tags import TagService
    from app.infrastructure.database.pool_capacity_cache import SqliteCapacityCache
    from app.presentation.components.application_workspace import ApplicationWorkspace
    from app.presentation.components.planning_workspace import PlanningWorkspace
    from app.presentation.components.project_workspace import ProjectWorkspace
    from app.presentation.components.settings_workspace import SettingsWorkspace

from app import main as application
from app.infrastructure.database.operator_context import deployment_access


def create_pool_capacity_cache(db_path: str | None = None) -> SqliteCapacityCache:
    """Compose pool capacity cache for a trusted deployment operator."""
    return application.create_pool_capacity_cache(db_path, access=deployment_access())


def create_pool_capacity_service(db_path: str | None = None) -> PoolCapacityService:
    """Compose pool capacity service for a trusted deployment operator."""
    return application.create_pool_capacity_service(db_path, access=deployment_access())


def create_planning_service(db_path: str | None = None) -> PlanningService:
    """Compose planning service for a trusted deployment operator."""
    return application.create_planning_service(db_path, access=deployment_access())


def create_tag_service(db_path: str | None = None) -> TagService:
    """Compose tag service for a trusted deployment operator."""
    return application.create_tag_service(db_path, access=deployment_access())


def create_resource_pool_service(db_path: str | None = None) -> ResourcePoolService:
    """Compose resource pool service for a trusted deployment operator."""
    return application.create_resource_pool_service(db_path, access=deployment_access())


def create_organization_service(db_path: str | None = None) -> OrganizationService:
    """Compose organization service for a trusted deployment operator."""
    return application.create_organization_service(db_path, access=deployment_access())


def create_project_type_service(db_path: str | None = None) -> ProjectTypeService:
    """Compose project type service for a trusted deployment operator."""
    return application.create_project_type_service(db_path, access=deployment_access())


def create_schema_service(db_path: str | None = None) -> SchemaService:
    """Compose schema service for a trusted deployment operator."""
    return application.create_schema_service(db_path, access=deployment_access())


def create_project_service(db_path: str | None = None) -> ProjectService:
    """Compose project service for a trusted deployment operator."""
    return application.create_project_service(db_path, access=deployment_access())


def create_portfolio_service(db_path: str | None = None, *, include_allocations: bool = True) -> PortfolioService:
    """Compose portfolio service for a trusted deployment operator."""
    return application.create_portfolio_service(db_path, access=deployment_access(), include_allocations=include_allocations)


def create_project_overallocation_service(db_path: str | None = None) -> ProjectOverallocationService:
    """Compose project overallocation service for a trusted deployment operator."""
    return application.create_project_overallocation_service(db_path, access=deployment_access())


def create_project_workspace(db_path: str | None = None) -> ProjectWorkspace:
    """Compose project workspace for a trusted deployment operator."""
    return application.create_project_workspace(db_path, access=deployment_access())


def create_collaboration_service(db_path: str | None = None) -> CollaborationService:
    """Compose collaboration service for a trusted deployment operator."""
    return application.create_collaboration_service(db_path, access=deployment_access())


def create_budget_service(db_path: str | None = None) -> BudgetService:
    """Compose budget service for a trusted deployment operator."""
    return application.create_budget_service(db_path, access=deployment_access())


def create_settings_workspace(db_path: str | None = None) -> SettingsWorkspace:
    """Compose settings workspace for a trusted deployment operator."""
    return application.create_settings_workspace(db_path, access=deployment_access())


def create_application_workspace(db_path: str | None = None, *, authentication: AccessService | None = None) -> ApplicationWorkspace:
    """Compose application workspace for a trusted deployment operator."""
    return application.create_application_workspace(db_path, access=deployment_access(), authentication=authentication)


def create_planning_workspace(db_path: str | None = None) -> PlanningWorkspace:
    """Compose planning workspace for a trusted deployment operator."""
    return application.create_planning_workspace(db_path, access=deployment_access())


def create_maintenance_service(db_path: str | None = None) -> MaintenanceService:
    """Compose database maintenance for deployment commands and test fixtures."""
    from app.application.services.maintenance import MaintenanceService
    from app.infrastructure.database.maintenance import SqliteMaintenanceGateway

    return MaintenanceService(SqliteMaintenanceGateway(db_path))
