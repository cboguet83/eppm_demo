"""Injected dependencies for the lazy Settings sections."""

from dataclasses import dataclass

from app.application.services.collaboration import CollaborationService
from app.application.services.organization import OrganizationService
from app.application.services.pool_capacity import PoolCapacityService
from app.application.services.project_types import ProjectTypeService
from app.application.services.resource_pools import ResourcePoolService
from app.application.services.schema import SchemaService
from app.application.services.tags import TagService


@dataclass(frozen=True)
class SettingsWorkspace:
    """Services composed outside presentation for the existing Settings tabs."""

    organization: OrganizationService
    tags: TagService
    resources: ResourcePoolService
    capacity: PoolCapacityService
    schema: SchemaService
    types: ProjectTypeService
    collaboration: CollaborationService
