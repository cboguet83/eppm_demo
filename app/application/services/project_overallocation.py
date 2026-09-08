"""Portfolio overload indicators composed from planning and capacity use cases."""

from app.application.services.planning import PlanningService
from app.application.services.pool_capacity import PoolCapacityService
from app.domain.resources.overallocation import overloaded_consumers


class ProjectOverallocationService:
    """Limit capacity reads to positive-demand pools relevant to a portfolio page."""

    def __init__(self, planning: PlanningService, capacity: PoolCapacityService) -> None:
        """Inject the pool-scope query and shared capacity service."""
        self._planning = planning
        self._capacity = capacity

    def overallocated_project_ids(self, project_ids: list[int]) -> set[int]:
        """Return only requested projects consuming capacity on an overloaded day."""
        requested = set(project_ids)
        if not requested:
            return set()
        pool_ids = self._planning.consuming_pool_ids(sorted(requested))
        if not pool_ids:
            return set()
        overloaded = [
            pool.pool_id for pool in self._capacity.get_summaries(pool_ids) if pool.is_overassigned
        ]
        if not overloaded:
            return set()
        return overloaded_consumers(self._capacity.get_details(overloaded), requested)
