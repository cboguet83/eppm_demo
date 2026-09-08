"""Injected application dependencies for planning screens and their caches."""

from dataclasses import dataclass

from app.application.services.organization import OrganizationService
from app.application.services.planning import PlanningService
from app.application.services.pool_capacity import PoolCapacityService
from app.application.services.resource_pools import ResourcePoolService
from app.application.services.schema import SchemaService
from app.application.services.tags import TagService
from app.domain.resources.models import PoolCapacityDetail
from app.presentation.components.project_workspace import ProjectWorkspace


@dataclass(frozen=True)
class PlanningWorkspace:
    """Services assembled in the composition root, without UI-owned repositories."""

    planning: PlanningService
    tags: TagService
    resources: ResourcePoolService
    capacity: PoolCapacityService
    organization: OrganizationService
    schema: SchemaService
    projects: ProjectWorkspace

    def revision(self) -> tuple:
        """Include the source database identity in every display-cache key."""
        return self.projects.portfolio.revision()

    def pool_details(self, pool_ids: list[int] | None = None) -> list[PoolCapacityDetail]:
        """Read cached details for explicit pools or the initial full capacity grid."""
        if pool_ids is None:
            pool_ids = [pool.pool_id for pool in self.capacity.get_summaries()]
        return self.capacity.get_details(list(pool_ids))
