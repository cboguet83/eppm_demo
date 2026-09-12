"""Resource-pool use cases and atomic catalog/group/tag operations."""

from app.domain.access.models import Permission
from app.domain.hierarchy import HierarchyType
from app.application.ports.references import PoolReference, PoolGroupReference


from dataclasses import asdict

from app.application.ports.resource_pools import ResourcePoolGateway, ResourcePoolStore
from app.domain.resources.models import (
    AssignmentLink,
    AssignmentRow,
    PoolAssignment,
    PoolGroupMemberRow,
    PoolGroupSummary,
    PoolMapping,
    PoolTag,
    PoolTagChoice,
    ResourcePool,
    ResourcePoolGroup,
    ResourcePoolGroupMember,
)
from app.domain.resources.rules import (
    descendant_groups,
    descendant_pools,
    normalize_assignment,
    normalize_group,
    normalize_mapping,
    normalize_pool,
    validate_allocation_pct,
    validate_group_children,
)


class ResourcePoolService:
    """Apply pool rules through complete authorized transaction callbacks."""

    def __init__(self, gateway: ResourcePoolGateway) -> None:
        """Inject persistence without acquiring a database connection."""
        self._gateway = gateway

    def pool_choices(self) -> list[PoolReference]:
        """Read allocation-selector labels without pool configuration details."""
        return self._gateway.run(lambda store: [PoolReference(row.id, row.name, row.capacity_fte) for row in store.get_all_pools()])

    def group_choices(self) -> list[PoolGroupReference]:
        """Read group labels for planning filters and allocation selectors."""
        return self._gateway.run(lambda store: [PoolGroupReference(row.id, row.name) for row in store.groups()])

    def group_membership(self) -> list[ResourcePoolGroupMember]:
        """Read only graph identities needed to render recursive planning groups."""
        return self._gateway.run(lambda store: store.get_all_group_members())

    def group_pool_ids(self, group_id: int) -> list[int]:
        """Resolve selected group membership with deliberate cycle termination."""
        return self._gateway.run(lambda store: descendant_pools(group_id, store.get_all_group_members()))

    def get_all_pools(self) -> list[ResourcePool]:
        """Get all pools within one application transaction."""
        return self._gateway.run(lambda store: store.get_all_pools(), permission=Permission.SHARED)

    def get_all_hierarchy_types(self) -> list[HierarchyType]:
        """Read shared classifications for optional pool and group assignments."""
        return self._gateway.run(lambda store: store.get_all_hierarchy_types(), permission=Permission.SHARED)

    def get_pool_by_id(self, pool_id: int) -> ResourcePool | None:
        """Get pool by id within one application transaction."""
        return self._gateway.run(lambda store: store.get_pool_by_id(pool_id), permission=Permission.SHARED)

    def create_pool(self, pool: ResourcePool, *, tag_ids: list[int] | None = None) -> int:
        """Create pool within one application transaction."""
        pool = normalize_pool(pool)
        tag_ids = None if tag_ids is None else list(tag_ids)
        def operation(store: ResourcePoolStore) -> int:
            result = store.create_pool(pool)
            if result and tag_ids is not None:
                self._set_tags(store, result, tag_ids)
            return result
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def update_pool(self, pool: ResourcePool, *, tag_ids: list[int] | None = None) -> bool:
        """Update pool within one application transaction."""
        if pool.id is None:
            return False
        pool = normalize_pool(pool)
        tag_ids = None if tag_ids is None else list(tag_ids)
        def operation(store: ResourcePoolStore) -> bool:
            result = store.update_pool(pool)
            if result and tag_ids is not None:
                self._set_tags(store, pool.id, tag_ids)
            return result
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def delete_pool(self, pool_id: int) -> bool:
        """Delete pool within one application transaction."""
        return self._gateway.run(lambda store: store.delete_pool(pool_id), write=True, permission=Permission.SHARED)

    def get_all_group_members(self) -> list[ResourcePoolGroupMember]:
        """Get all group members within one application transaction."""
        return self._gateway.run(lambda store: store.get_all_group_members(), permission=Permission.SHARED)

    def get_pool_group_by_id(self, group_id: int) -> ResourcePoolGroup | None:
        """Get pool group by id within one application transaction."""
        return self._gateway.run(lambda store: store.get_pool_group_by_id(group_id), permission=Permission.SHARED)

    def create_pool_group(
        self,
        group: ResourcePoolGroup,
        *,
        pool_ids: list[int] | None = None,
        child_group_ids: list[int] | None = None,
    ) -> int:
        """Create pool group within one application transaction."""
        group = normalize_group(group)
        pool_ids = None if pool_ids is None else list(pool_ids)
        child_group_ids = None if child_group_ids is None else list(child_group_ids)
        def operation(store: ResourcePoolStore) -> int:
            result = store.create_pool_group(group)
            if result and (pool_ids is not None or child_group_ids is not None):
                self._replace_members(store, result, pool_ids or [], child_group_ids or [])
            return result
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def update_pool_group(
        self,
        group: ResourcePoolGroup,
        *,
        pool_ids: list[int] | None = None,
        child_group_ids: list[int] | None = None,
    ) -> bool:
        """Update pool group within one application transaction."""
        if group.id is None:
            return False
        group = normalize_group(group)
        pool_ids = None if pool_ids is None else list(pool_ids)
        child_group_ids = None if child_group_ids is None else list(child_group_ids)
        def operation(store: ResourcePoolStore) -> bool:
            result = store.update_pool_group(group)
            if result and (pool_ids is not None or child_group_ids is not None):
                self._replace_members(store, group.id, pool_ids or [], child_group_ids or [])
            return result
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def delete_pool_group(self, group_id: int) -> bool:
        """Delete pool group within one application transaction."""
        return self._gateway.run(lambda store: store.delete_pool_group(group_id), write=True, permission=Permission.SHARED)

    def get_group_members(self, group_id: int) -> list[PoolGroupMemberRow]:
        """Get group members within one application transaction."""
        return self._gateway.run(lambda store: store.get_group_members(group_id), permission=Permission.SHARED)

    def get_mappings_by_pool(self, pool_id: int) -> list[PoolMapping]:
        """Get mappings by pool within one application transaction."""
        return self._gateway.run(lambda store: store.get_mappings_by_pool(pool_id), permission=Permission.SHARED)

    def get_all_mappings(self) -> list[PoolMapping]:
        """Get all mappings within one application transaction."""
        return self._gateway.run(lambda store: store.get_all_mappings(), permission=Permission.SHARED)

    def create_mapping(self, mapping: PoolMapping) -> int:
        """Create mapping within one application transaction."""
        mapping = normalize_mapping(mapping)
        return self._gateway.run(lambda store: store.create_mapping(mapping), write=True, permission=Permission.SHARED)

    def update_mapping(self, mapping_id: int, allocation_pct: float) -> bool:
        """Update mapping within one application transaction."""
        validate_allocation_pct(allocation_pct)
        return self._gateway.run(lambda store: store.update_mapping(mapping_id, allocation_pct), write=True, permission=Permission.SHARED)

    def delete_mapping(self, mapping_id: int) -> bool:
        """Delete mapping within one application transaction."""
        return self._gateway.run(lambda store: store.delete_mapping(mapping_id), write=True, permission=Permission.SHARED)

    def get_assignments(
        self,
        pool_id: int | None = None,
        project_id: int | None = None,
        task_id: int | None = None,
        only_project_level: bool = False,
    ) -> list[AssignmentRow]:
        """Get assignments within one application transaction."""
        return self._gateway.run(lambda store: store.get_assignments(pool_id, project_id, task_id, only_project_level))

    def get_assignment_by_id(self, assignment_id: int) -> PoolAssignment | None:
        """Get assignment by id within one application transaction."""
        return self._gateway.run(lambda store: store.get_assignment_by_id(assignment_id))

    def create_assignment(self, assignment: PoolAssignment) -> int:
        """Create assignment within one application transaction."""
        assignment = normalize_assignment(assignment)
        return self._gateway.run(lambda store: store.create_assignment(assignment), write=True)

    def update_assignment(self, assignment: PoolAssignment) -> bool:
        """Update assignment within one application transaction."""
        if assignment.id is None:
            return False
        assignment = normalize_assignment(assignment)
        return self._gateway.run(lambda store: store.update_assignment(assignment), write=True)

    def delete_assignment(self, assignment_id: int) -> bool:
        """Delete assignment within one application transaction."""
        return self._gateway.run(lambda store: store.delete_assignment(assignment_id), write=True)

    def get_task_assignments_map(self, task_ids: list[int]) -> dict[int, list[AssignmentLink]]:
        """Get task assignments map within one application transaction."""
        task_ids = list(task_ids)
        return self._gateway.run(lambda store: store.get_task_assignments_map(task_ids))

    def get_project_assignments_map(
        self, project_ids: list[int]
    ) -> dict[int, list[AssignmentLink]]:
        """Get project assignments map within one application transaction."""
        project_ids = list(project_ids)
        return self._gateway.run(lambda store: store.get_project_assignments_map(project_ids))

    def get_tag_choices(self) -> list[PoolTagChoice]:
        """Get tag choices within one application transaction."""
        return self._gateway.run(lambda store: store.get_tag_choices(), permission=Permission.SHARED)

    def get_pool_tags(self, pool_id: int) -> list[PoolTag]:
        """Get pool tags within one application transaction."""
        return self._gateway.run(lambda store: store.get_pool_tags(pool_id), permission=Permission.SHARED)

    def get_all_pool_groups(self) -> list[PoolGroupSummary]:
        """Read counts and the complete graph in one consistent snapshot."""
        def operation(store: ResourcePoolStore) -> list[PoolGroupSummary]:
            groups, members = store.groups(), store.get_all_group_members()
            return [
                PoolGroupSummary(
                    **asdict(group),
                    direct_pool_count=sum(
                        m.pool_id is not None for m in members if m.group_id == group.id
                    ),
                    child_group_count=sum(
                        m.child_group_id is not None for m in members if m.group_id == group.id
                    ),
                    recursive_pool_count=len(descendant_pools(group.id, members)),
                )
                for group in groups
            ]
        return self._gateway.run(operation, permission=Permission.SHARED)

    def get_group_direct_member_ids(self, group_id: int) -> tuple[list[int], list[int]]:
        """Read direct pool and child IDs in the historical display order."""
        members = self.get_group_members(group_id)
        return (
            [m.pool_id for m in members if m.pool_id is not None],
            [m.child_group_id for m in members if m.child_group_id is not None],
        )

    def get_group_descendant_pool_ids(self, group_id: int) -> list[int]:
        """Resolve the full graph with deliberate cycle termination."""
        return self._gateway.run(lambda store: descendant_pools(group_id, store.get_all_group_members()), permission=Permission.SHARED)

    def would_create_group_cycle(self, group_id: int, child_group_id: int) -> bool:
        """Preview whether a proposed child can already reach its parent."""
        return self._gateway.run(lambda store: int(group_id) in descendant_groups(int(child_group_id), store.get_all_group_members()), permission=Permission.SHARED)

    def get_allowed_child_group_ids(self, group_id: int) -> list[int]:
        """Read the graph once for the editor's child-group choices."""
        def operation(store: ResourcePoolStore) -> list[int]:
            members = store.get_all_group_members()
            return [
                group.id
                for group in store.groups()
                if group_id not in descendant_groups(group.id, members)
            ]
        return self._gateway.run(operation, permission=Permission.SHARED)

    def replace_group_members(
        self, group_id: int, pool_ids: list[int], child_group_ids: list[int]
    ) -> None:
        """Revalidate all new graph edges inside each complete write attempt."""
        pool_ids, child_group_ids = list(pool_ids), list(child_group_ids)
        def operation(store: ResourcePoolStore) -> None:
            self._replace_members(store, group_id, pool_ids, child_group_ids)
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    @staticmethod
    def _replace_members(
        store: ResourcePoolStore, group_id: int, pool_ids: list[int], child_ids: list[int]
    ) -> None:
        pools, children = sorted(set(map(int, pool_ids))), sorted(set(map(int, child_ids)))
        groups = {group.id for group in store.groups()}
        if group_id not in groups:
            raise ValueError(f"Pool group #{group_id} does not exist.")
        missing_pools = set(pools) - {pool.id for pool in store.get_all_pools()}
        if missing_pools:
            raise ValueError(f"Unknown resource pool IDs: {sorted(missing_pools)}")
        if set(children) - groups:
            raise ValueError(f"Unknown pool group IDs: {sorted(set(children) - groups)}")
        validate_group_children(group_id, children, store.get_all_group_members())
        store.replace_group_members(group_id, pools, children)

    def set_pool_tags(self, pool_id: int, tag_ids: list[int]) -> None:
        """Replace tags atomically after checking their current references."""
        tag_ids = list(tag_ids)
        def operation(store: ResourcePoolStore) -> None:
            self._set_tags(store, pool_id, tag_ids)
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    @staticmethod
    def _set_tags(store: ResourcePoolStore, pool_id: int, tag_ids: list[int]) -> None:
        tags = sorted(set(map(int, tag_ids)))
        if store.get_pool_by_id(pool_id) is None:
            raise ValueError(f"Resource pool #{pool_id} does not exist.")
        missing = set(tags) - {tag.id for tag in store.get_tag_choices()}
        if missing:
            raise ValueError(f"Unknown dictionary tag IDs: {sorted(missing)}")
        store.set_pool_tags(pool_id, tags)
