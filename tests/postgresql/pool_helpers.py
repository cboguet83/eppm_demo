"""Small fixture builders for tests that need an existing pool container."""

from dataclasses import replace

from app.application.services.resource_pools import ResourcePoolService
from app.domain.resources.models import ResourcePool


def create_container(service: ResourcePoolService, pool: ResourcePool, *,
                     pool_ids: list[int] | None = None, child_group_ids: list[int] | None = None) -> int:
    """Build test ancestry through the same Python services used by the UI."""
    identity = service.create_pool(pool)
    for child in (pool_ids or []) + (child_group_ids or []):
        service.update_pool(replace(service.get_pool_by_id(child), parent_pool_id=identity))
    return identity
