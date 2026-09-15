"""Capacity use cases with injected persistence, cache, and calendar day."""

from collections.abc import Callable
from dataclasses import fields, replace
from datetime import date
from typing import cast

from app.application.ports.pool_capacity import CapacityCache, CapacityReader
from app.application.exceptions import ResourcePoolStorageError
from app.domain.resources.capacity import calculate_capacity
from app.domain.resources.container_capacity import aggregate_capacity
from app.domain.resources.hierarchy import PoolHierarchy
from app.domain.resources.allocation_scope import scope_pool_detail
from app.domain.resources.models import PoolCapacityDetail, PoolCapacitySummary
from app.domain.planning.plans import PlanContent
from app.domain.planning.plan_comparison import scenario_capacity


class PoolCapacityService:
    """Calculate pure capacity models from a consistent shared input snapshot."""

    def __init__(
        self,
        reader: CapacityReader,
        cache: CapacityCache,
        today: Callable[[], date],
    ) -> None:
        """Inject the snapshot reader, derived-data cache, and effective-day clock."""
        self._reader = reader
        self._cache = cache
        self._today = today

    def calculate_many(
        self,
        pool_ids: list[int],
        on_date: date | None = None,
    ) -> list[PoolCapacityDetail]:
        """Read all requested inputs once and evaluate on the same day."""
        pool_ids = list(pool_ids)
        day = on_date if on_date is not None else self._today()
        inputs = self._reader.read(pool_ids)
        tree = PoolHierarchy(replace(item.pool, parent_pool_id=item.pool.parent_pool_id
                                    if item.pool.parent_pool_id in inputs else None)
                             for item in inputs.values() if item.pool is not None)
        leaves = {identity: calculate_capacity(item, day) for identity, item in inputs.items()
                  if not tree.children.get(identity)}
        return self._reader.visible_details(
            [aggregate_capacity(tree.pools[identity], [leaves[leaf] for leaf in tree.descendants(identity, leaves_only=True)])
             if tree.children.get(identity) else leaves[identity] for identity in pool_ids]
        )

    def get_summaries(self, pool_ids: list[int] | None = None) -> list[PoolCapacitySummary]:
        """Read cached leaf summaries and calculate date-aligned container totals."""
        return cast(list[PoolCapacitySummary], self._load(pool_ids, details=False))

    def get_details(self, pool_ids: list[int], *, project_ids: set[int] | None = None) -> list[PoolCapacityDetail]:
        """Return full details only for explicitly requested pools."""
        return cast(list[PoolCapacityDetail], self._load(pool_ids, details=True, project_ids=project_ids))

    def compare_plan_capacity(self, pool_ids: list[int], reference: dict[int, PlanContent],
                              alternative: dict[int, PlanContent], names: dict[int, str]
                              ) -> tuple[list[PoolCapacityDetail], list[PoolCapacityDetail]]:
        """Evaluate both plan selections against one shared live-capacity snapshot."""
        details = self.get_details(pool_ids)
        today = self._today()
        return (scenario_capacity(details, reference, names, today),
                scenario_capacity(details, alternative, names, today))

    def current_capacities(self, hierarchy: PoolHierarchy, details: list[PoolCapacityDetail],
                           mapped_pool_ids: set[int]) -> dict[int, float]:
        """Calculate today's staffing or fallback capacity, then sum container leaves.

        Any mapping selects staffing, including an empty team or zero availability.
        Unmapped leaves use defined capacity reduced by their pool exceptions.
        """
        day = self._today().isoformat()
        leaves = {row.pool_id: self._capacity_on_date(row, day, mapped_pool_ids)
                  for row in details if not hierarchy.children.get(row.pool_id)}
        return {identity: round(sum(leaves.get(leaf, 0) for leaf in hierarchy.descendants(identity, leaves_only=True)), 3)
                for identity in hierarchy.pools}

    @staticmethod
    def _capacity_on_date(detail: PoolCapacityDetail, day: str, mapped_pool_ids: set[int]) -> float:
        """Use the same staffing or pool-exception rule for any calendar date."""
        if detail.pool_id in mapped_pool_ids:
            return detail.daily_assigned_capacity.get(day, detail.assigned_capacity_fte)
        return detail.capacity_calendar.get(day, detail.effective_capacity_fte)

    def peak_date_capacities(self, hierarchy: PoolHierarchy, details: list[PoolCapacityDetail],
                             mapped_pool_ids: set[int]) -> dict[int, float]:
        """Return available capacity on each pool's future peak-demand dates.

        Containers sum their leaves on the container's peak date. If peak demand
        repeats, use the lowest capacity across those dates so any peak shortage
        is flagged. Pools without positive future demand return zero.
        """
        today = self._today().isoformat()
        by_id = {row.pool_id: row for row in details}
        result: dict[int, float] = {}
        for row in details:
            future = {day: value for day, value in row.daily_usage.items() if day >= today}
            peak = max(future.values(), default=0)
            leaves = [by_id[identity] for identity in hierarchy.descendants(row.pool_id, leaves_only=True)]
            result[row.pool_id] = round(min((
                sum(self._capacity_on_date(leaf, day, mapped_pool_ids) for leaf in leaves)
                for day, value in future.items() if value == peak and peak > 0
            ), default=0), 3)
        return result

    def future_peak_demand(self, details: list[PoolCapacityDetail]) -> float:
        """Return the maximum combined required FTE from today onward.

        Demand is summed on the same date before selecting the peak. Callers
        pass disjoint pools already scoped to the selected project statuses.
        Past dates are excluded, and no future demand returns zero.
        """
        today = self._today().isoformat()
        demand: dict[str, float] = {}
        for detail in details:
            for day, required in detail.daily_usage.items():
                if day >= today:
                    demand[day] = demand.get(day, 0.0) + required
        return round(max(demand.values(), default=0.0), 3)

    def _load(self, pool_ids: list[int] | None, *, details: bool,
              project_ids: set[int] | None = None) -> list[PoolCapacityDetail] | list[PoolCapacitySummary]:
        """Cache leaves and rebuild containers, retrying if their ancestry changes.

        Parent cache entries would need every descendant's revision. Calculating
        rollups from already revision-checked leaves avoids stale parent totals.
        """
        for _ in range(3):
            pools = self._reader.pool_hierarchy()
            tree = PoolHierarchy(pools)
            selected = sorted(tree.pools if pool_ids is None else set(pool_ids) & tree.pools.keys())
            containers = {identity for identity in selected if tree.children.get(identity)}
            leaves = sorted({leaf for identity in selected for leaf in tree.descendants(identity, leaves_only=True)})
            full = details or bool(containers)
            rows = self._cache.load(self.calculate_many, pool_ids=leaves, details=full)
            if pools != self._reader.pool_hierarchy():
                continue
            if {row.pool_id for row in rows} != set(leaves):
                continue
            if not full:
                return rows
            by_id = {row.pool_id: scope_pool_detail(row, project_ids) if project_ids is not None else row for row in rows}
            for identity in containers:
                by_id[identity] = aggregate_capacity(tree.pools[identity],
                    [by_id[leaf] for leaf in tree.descendants(identity, leaves_only=True)])
            result = [by_id[identity] for identity in selected]
            if details:
                return self._reader.visible_details(result)
            names = {item.name for item in fields(PoolCapacitySummary)}
            return [PoolCapacitySummary(**{name: getattr(row, name) for name in names})
                    for row in result]
        raise ResourcePoolStorageError("The pool hierarchy changed during calculation. Please try again.")
