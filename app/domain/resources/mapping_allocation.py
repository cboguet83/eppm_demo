"""Cross-pool allocation limits using the existing employee deduplication rules."""

from dataclasses import dataclass, replace

from app.domain.resources.capacity import ResourceKey, resource_contributions
from app.domain.resources.inputs import CapacityInputs
from app.domain.resources.models import PoolMapping, ResourcePool


@dataclass
class MappingAllocations:
    """Active resource percentages by pool, independent of employee availability."""

    pools: dict[int, str]
    names: dict[ResourceKey, str]
    usage: dict[ResourceKey, dict[int, float]]

    def total(self, key: ResourceKey) -> float:
        """Return the total percentage across active pools."""
        return round(sum(self.usage.get(key, {}).values()), 6)

    @property
    def overallocated(self) -> set[ResourceKey]:
        """Return each employee or team exceeding 100% exactly once."""
        return {key for key in self.usage if self.total(key) > 100}

    def warning(self, key: ResourceKey) -> str:
        """Describe the total and every contributing pool for a warning overlay."""
        parts = [f'{self.pools[pool]}: {percentage:g}%'
                 for pool, percentage in self.usage.get(key, {}).items() if percentage > 0]
        return f'{self.names.get(key, key[0].title())}: {self.total(key):g}% allocated. ' + '; '.join(parts)

    def pool_warnings(self) -> dict[int, str]:
        """Describe overallocated mapped resources on every affected pool."""
        result: dict[int, list[str]] = {}
        for key in sorted(self.overallocated):
            for pool, percentage in self.usage[key].items():
                if percentage > 0:
                    result.setdefault(pool, []).append(self.warning(key))
        return {pool: '\n'.join(messages) for pool, messages in result.items()}

    def increased_overallocations(self, before: MappingAllocations) -> set[ResourceKey]:
        """Identify newly excessive or worsened totals, allowing existing repairs."""
        return {key for key in self.overallocated if self.total(key) > before.total(key)}


@dataclass
class MappingCatalog:
    """Authorized staffing catalog read within the mapping write transaction."""

    pools: list[ResourcePool]
    sources: CapacityInputs

    def capacity_inputs(self, mappings: list[PoolMapping] | None = None) -> dict[int, CapacityInputs]:
        """Build pool snapshots with one global direct-allocation context."""
        pools = {pool.id: pool for pool in self.pools if not pool.deleted_flag}
        live_employees = {person.employee_id for person in self.sources.employees if not person.deleted_flag}
        grouped: dict[int, list[PoolMapping]] = {}
        totals: dict[int, float] = {}
        for row in self.sources.mappings if mappings is None else mappings:
            if row.pool_id not in pools:
                continue
            grouped.setdefault(row.pool_id, []).append(row)
            if row.target_type == 'employee' and row.target_id in live_employees:
                totals[row.target_id] = totals.get(row.target_id, 0) + row.allocation_pct
        return {identity: replace(self.sources, pool_id=identity, pool=pool,
                    mappings=grouped.get(identity, []), direct_employee_totals=totals)
                for identity, pool in pools.items()}

    def allocations(self, mappings: list[PoolMapping] | None = None) -> MappingAllocations:
        """Sum teams and deduplicated employees across live pools in Python."""
        pools = {pool.id: pool for pool in self.pools if not pool.deleted_flag}
        teams = {team.team_id: team.team_name for team in self.sources.teams if not team.deleted_flag}
        names: dict[ResourceKey, str] = {('team', identity): name for identity, name in teams.items()}
        usage: dict[ResourceKey, dict[int, float]] = {}
        for pool_id, inputs in self.capacity_inputs(mappings).items():
            for row in inputs.mappings:
                if row.target_type == 'team' and row.target_id in teams:
                    usage.setdefault(('team', row.target_id), {})[pool_id] = row.allocation_pct
            for item in resource_contributions(inputs):
                if item.employee_id is not None:
                    key = ('employee', item.employee_id)
                    names[key] = item.resource_name
                    usage.setdefault(key, {})[pool_id] = item.effective_allocation_pct
        return MappingAllocations({identity: pool.name for identity, pool in pools.items()}, names, usage)

    def remaining(self, pool_id: int, kind: str, identity: int,
                  draft: list[PoolMapping] | None = None,
                  baseline: MappingAllocations | None = None) -> float:
        """Return the maximum replacement percentage, accounting for team members.

        The edited pool's existing mapping is replaced, not added again.
        Evaluate the whole catalog because direct changes affect other pools.
        """
        baseline = baseline if baseline is not None else self.allocations()
        rows = self.sources.mappings if draft is None else [
            row for row in self.sources.mappings if row.pool_id != pool_id or row.target_type == 'function'] + draft
        retained = [row for row in rows if (row.pool_id, row.target_type, row.target_id) != (pool_id, kind, identity)]
        if kind == 'employee':
            active_pools = {pool.id for pool in self.pools if not pool.deleted_flag}
            used = sum(row.allocation_pct for row in retained if row.pool_id in active_pools
                       and row.target_type == 'employee' and row.target_id == identity)
            return max(0, int(round((100 - used) * 1000, 6)) / 1000)
        def permitted(percentage: float) -> bool:
            candidate = self.allocations(retained + [PoolMapping(pool_id, kind, identity, percentage)])
            return all(candidate.total(key) <= max(100, baseline.total(key)) + 1e-9
                       for key in candidate.usage)
        if permitted(100):
            return 100.0
        lower, upper = 0, 100000
        while lower < upper:
            middle = (lower + upper + 1) // 2
            if permitted(middle / 1000):
                lower = middle
            else:
                upper = middle - 1
        return lower / 1000

    def limits(self, pool_id: int, draft: list[PoolMapping] | None = None) -> dict[ResourceKey, float]:
        """Calculate dropdown limits against one shared committed baseline."""
        baseline = self.allocations()
        keys = [('team', team.team_id) for team in self.sources.teams if not team.deleted_flag]
        keys += [('employee', person.employee_id) for person in self.sources.employees if not person.deleted_flag]
        return {key: self.remaining(pool_id, *key, draft=draft, baseline=baseline) for key in keys}

    def validate(self, mappings: list[PoolMapping]) -> None:
        """Reject new or increased overallocation; allow repairing restored pools."""
        before, after = self.allocations(), self.allocations(mappings)
        for key in sorted(after.increased_overallocations(before)):
            raise ValueError('Allocation cannot exceed 100% across active pools. ' + after.warning(key))
