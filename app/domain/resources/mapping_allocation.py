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


@dataclass
class MappingCatalog:
    """Authorized staffing catalog read within the mapping write transaction."""

    pools: list[ResourcePool]
    sources: CapacityInputs

    def allocations(self, mappings: list[PoolMapping] | None = None) -> MappingAllocations:
        """Sum teams and deduplicated employees across live pools in Python."""
        pools = {pool.id: pool for pool in self.pools if not pool.deleted_flag}
        teams = {team.team_id: team.team_name for team in self.sources.teams if not team.deleted_flag}
        names: dict[ResourceKey, str] = {('team', identity): name for identity, name in teams.items()}
        usage: dict[ResourceKey, dict[int, float]] = {}
        grouped: dict[int, list[PoolMapping]] = {}
        for mapping in self.sources.mappings if mappings is None else mappings:
            if mapping.pool_id in pools:
                grouped.setdefault(mapping.pool_id, []).append(mapping)
        for pool_id, rows in grouped.items():
            for row in rows:
                if row.target_type == 'team' and row.target_id in teams:
                    usage.setdefault(('team', row.target_id), {})[pool_id] = row.allocation_pct
            inputs = replace(self.sources, pool_id=pool_id, pool=pools[pool_id], mappings=rows)
            for item in resource_contributions(inputs):
                if item.employee_id is not None:
                    key = ('employee', item.employee_id)
                    names[key] = item.resource_name
                    usage.setdefault(key, {})[pool_id] = item.effective_allocation_pct
        return MappingAllocations({identity: pool.name for identity, pool in pools.items()}, names, usage)

    def remaining(self, pool_id: int, kind: str, identity: int,
                  draft: list[PoolMapping] | None = None,
                  outside: MappingAllocations | None = None) -> float:
        """Return the maximum replacement percentage, accounting for team members.

        The edited pool's existing mapping is replaced, not added again. Other
        mappings in that pool retain direct-employee and team deduplication rules.
        """
        outside = outside if outside is not None else self.allocations([
            row for row in self.sources.mappings if row.pool_id != pool_id])
        rows = self.sources.mappings if draft is None else draft
        retained = [row for row in rows if row.pool_id == pool_id and
                    (row.target_type, row.target_id) != (kind, identity)]
        low = self.allocations(retained + [PoolMapping(pool_id, kind, identity, 0)])
        def permitted(percentage: float) -> bool:
            candidate = self.allocations(retained + [PoolMapping(pool_id, kind, identity, percentage)])
            return all(candidate.total(key) <= max(100 - outside.total(key), low.total(key)) + 1e-9
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
        """Calculate dropdown limits with one shared outside-pool projection."""
        outside = self.allocations([row for row in self.sources.mappings if row.pool_id != pool_id])
        keys = [('team', team.team_id) for team in self.sources.teams if not team.deleted_flag]
        keys += [('employee', person.employee_id) for person in self.sources.employees if not person.deleted_flag]
        return {key: self.remaining(pool_id, *key, draft=draft, outside=outside) for key in keys}

    def validate(self, mappings: list[PoolMapping]) -> None:
        """Reject new or increased overallocation; allow repairing restored pools."""
        before, after = self.allocations(), self.allocations(mappings)
        for key in sorted(after.overallocated):
            if after.total(key) > before.total(key):
                raise ValueError('Allocation cannot exceed 100% across active pools. ' + after.warning(key))
