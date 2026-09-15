"""Resource-pool use cases and atomic catalog/hierarchy/tag operations."""

from dataclasses import replace
from datetime import date
from math import isfinite

from app.domain.access.models import Permission
from app.domain.hierarchy import HierarchyType
from app.domain.resources.pool_types import PoolType, normalize_pool_type
from app.domain.resources.hierarchy import PoolHierarchy
from app.application.ports.references import PoolReference, PoolGroupReference, PoolHierarchyMember
from app.application.ports.resource_pools import ResourcePoolGateway, ResourcePoolStore
from app.domain.resources.models import (
    AssignmentLink,
    AssignmentRow,
    PoolAssignment,
    PoolCapacityException,
    PoolMapping,
    PoolTag,
    PoolTagChoice,
    ResourcePool,
)
from app.domain.resources.rules import (
    normalize_assignment,
    normalize_mapping,
    normalize_pool,
    validate_allocation_pct,
)


class ResourcePoolService:
    """Apply pool rules through complete authorized transaction callbacks."""

    def __init__(self, gateway: ResourcePoolGateway) -> None:
        """Inject persistence without acquiring a database connection."""
        self._gateway = gateway

    def pool_choices(self) -> list[PoolReference]:
        """Read allocation-selector labels without pool configuration details."""
        def operation(store: ResourcePoolStore) -> list[PoolReference]:
            tree = PoolHierarchy(store.get_all_pools())
            return [PoolReference(row.id, row.name, row.capacity_fte)
                    for row in tree.pools.values() if not tree.children.get(row.id)]
        return self._gateway.run(operation)

    def descendant_pool_ids(self, pool_id: int) -> list[int]:
        """Resolve assignable leaves; a deleted selection has no descendants."""
        def operation(store: ResourcePoolStore) -> list[int]:
            tree = PoolHierarchy(store.get_all_pools())
            return tree.descendants(pool_id, leaves_only=True) if pool_id in tree.pools else []
        return self._gateway.run(operation)

    def parent_pool_warning(self, pool_id: int) -> str | None:
        """Preview why a parent cannot receive children; writes always recheck."""
        def operation(store: ResourcePoolStore) -> str | None:
            tree = PoolHierarchy(store.get_all_pools())
            try:
                self._require_parent_available(store, tree, pool_id)
            except ValueError as error:
                return str(error)
            return None
        return self._gateway.run(operation, permission=Permission.SHARED)

    @staticmethod
    def _require_parent_available(store: ResourcePoolStore, tree: PoolHierarchy, pool_id: int) -> None:
        """Protect assignments and direct resource configuration during conversion."""
        pool = tree.pools.get(pool_id)
        if pool is None:
            raise ValueError("The parent pool no longer exists.")
        if pool_id in store.assigned_pool_ids():
            raise ValueError(f'Cannot add a child to “{pool.name}”: this pool has project or task assignments. '
                             'Remove or reassign them before adding children.')
        if store.get_mappings_by_pool(pool_id) or store.capacity_exceptions([pool_id]):
            raise ValueError(f'Cannot add a child to “{pool.name}”: move or remove its resource mappings '
                             'and capacity exceptions first. Containers use their children’s capacity.')

    @classmethod
    def _validate_pool_save(cls, store: ResourcePoolStore, pool: ResourcePool) -> ResourcePool:
        """Validate the proposed forest and conversion within the write snapshot."""
        existing = store.get_all_pools()
        tree = PoolHierarchy(existing)
        if pool.id is not None and tree.children.get(pool.id):
            if pool.capacity_fte not in (None, 0):
                raise ValueError("Container capacity is calculated from its children and cannot be edited.")
            pool = replace(pool, capacity_fte=0.0)
        proposed_id = pool.id if pool.id is not None else max(tree.pools, default=0) + 1
        PoolHierarchy([row for row in existing if row.id != pool.id] + [replace(pool, id=proposed_id)])
        previous = tree.pools.get(pool.id)
        if pool.parent_pool_id is not None and (previous is None or previous.parent_pool_id != pool.parent_pool_id):
            cls._require_parent_available(store, tree, pool.parent_pool_id)
            parent = tree.pools[pool.parent_pool_id]
            # An unchanged update still advances the existing pool revision.
            # Invalidate any former leaf cache when the node changes role.
            store.update_pool(replace(parent, capacity_fte=0.0))
        if previous is not None and previous.parent_pool_id is not None and previous.parent_pool_id != pool.parent_pool_id:
            store.update_pool(tree.pools[previous.parent_pool_id])
        return pool

    def capacity_exceptions(self, pool_id: int) -> list[PoolCapacityException]:
        """Read the selected pool's absolute-capacity reduction periods."""
        return self._gateway.run(lambda store: store.capacity_exceptions([pool_id]))

    @staticmethod
    def _normalize_capacity_exception(item: PoolCapacityException) -> PoolCapacityException:
        """Validate and normalize an inclusive capacity reduction."""
        first, last = date.fromisoformat(item.start_date), date.fromisoformat(item.end_date)
        if not 0 <= (last - first).days < 9125:
            raise ValueError('The exception must end on or after its start and span at most 9125 days.')
        if not isfinite(item.reduction_fte) or not 0.001 <= item.reduction_fte < 1_000_000_000:
            raise ValueError('Enter a positive finite capacity reduction in FTE.')
        return replace(item, reduction_fte=round(item.reduction_fte, 3), reason=item.reason.strip())

    def save_capacity_exception(self, item: PoolCapacityException) -> int:
        """Validate an inclusive reduction and authorize shared configuration edits."""
        item = self._normalize_capacity_exception(item)
        def operation(store: ResourcePoolStore) -> int:
            PoolHierarchy(store.get_all_pools()).require_leaf(item.pool_id)
            return store.save_capacity_exception(item)
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def delete_capacity_exception(self, identity: int) -> bool:
        """Remove an exception after current shared-management authorization."""
        return self._gateway.run(lambda store: store.delete_capacity_exception(identity), write=True, permission=Permission.SHARED)

    def group_choices(self) -> list[PoolGroupReference]:
        """Project container labels into the existing planning transport contract."""
        def operation(store: ResourcePoolStore) -> list[PoolGroupReference]:
            tree = PoolHierarchy(store.get_all_pools())
            return [PoolGroupReference(row.id, row.name) for row in tree.pools.values()
                    if tree.children.get(row.id)]
        return self._gateway.run(operation)

    def group_membership(self) -> list[PoolHierarchyMember]:
        """Adapt pool ancestry to the existing Gantt container/leaf wire format."""
        def operation(store: ResourcePoolStore) -> list[PoolHierarchyMember]:
            tree = PoolHierarchy(store.get_all_pools())
            return [PoolHierarchyMember(row.parent_pool_id,
                        pool_id=None if tree.children.get(row.id) else row.id,
                        child_group_id=row.id if tree.children.get(row.id) else None)
                    for row in tree.pools.values() if row.parent_pool_id is not None]
        return self._gateway.run(operation)

    def group_pool_ids(self, group_id: int) -> list[int]:
        """Resolve a container ID carried by existing planning events."""
        return self.descendant_pool_ids(group_id)

    def get_all_pool_types(self) -> list[PoolType]:
        """Read the shared pool classification catalog in one transaction."""
        return self._gateway.run(lambda store: store.get_all_pool_types(), permission=Permission.SHARED)

    def save_pool_type(self, item: PoolType) -> int:
        """Validate ancestry and save a type with its translations atomically."""
        def operation(store: ResourcePoolStore) -> int:
            normalized = normalize_pool_type(item, store.get_all_pool_types())
            return store.save_pool_type(normalized)
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def delete_pool_type(self, identity: int) -> bool:
        """Delete an unused leaf type; database references protect pools and children."""
        return self._gateway.run(lambda store: store.delete_pool_type(identity), write=True, permission=Permission.SHARED)

    def get_all_pools(self) -> list[ResourcePool]:
        """Get all pools within one application transaction."""
        return self._gateway.run(lambda store: store.get_all_pools(), permission=Permission.SHARED)

    def get_all_hierarchy_types(self) -> list[HierarchyType]:
        """Read shared classifications for optional pool and group assignments."""
        return self._gateway.run(lambda store: store.get_all_hierarchy_types(), permission=Permission.SHARED)

    def get_pool_by_id(self, pool_id: int) -> ResourcePool | None:
        """Get pool by id within one application transaction."""
        return self._gateway.run(lambda store: store.get_pool_by_id(pool_id), permission=Permission.SHARED)

    def create_pool(self, pool: ResourcePool, *, tag_ids: list[int] | None = None,
                    capacity_exceptions: list[PoolCapacityException] | None = None) -> int:
        """Create a pool, tags and optional initial reductions atomically."""
        pool = normalize_pool(pool)
        tag_ids = None if tag_ids is None else list(tag_ids)
        exceptions = [self._normalize_capacity_exception(replace(item, id=None))
                      for item in capacity_exceptions or []]
        def operation(store: ResourcePoolStore) -> int:
            validated = self._validate_pool_save(store, pool)
            result = store.create_pool(validated)
            if result and tag_ids is not None:
                self._set_tags(store, result, tag_ids)
            for item in exceptions:
                store.save_capacity_exception(replace(item, pool_id=result))
            return result
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def update_pool(self, pool: ResourcePool, *, tag_ids: list[int] | None = None) -> bool:
        """Update pool within one application transaction."""
        if pool.id is None:
            return False
        pool = normalize_pool(pool)
        tag_ids = None if tag_ids is None else list(tag_ids)
        def operation(store: ResourcePoolStore) -> bool:
            if store.get_pool_by_id(pool.id) is None:
                return False
            validated = self._validate_pool_save(store, pool)
            result = store.update_pool(validated)
            if result and tag_ids is not None:
                self._set_tags(store, pool.id, tag_ids)
            return result
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def delete_pool(self, pool_id: int) -> bool:
        """Delete pool within one application transaction."""
        def operation(store: ResourcePoolStore) -> bool:
            tree = PoolHierarchy(store.get_all_pools())
            if tree.children.get(pool_id):
                raise ValueError("Move or delete this pool’s children before deleting the container.")
            pool = tree.pools.get(pool_id)
            if pool is not None and pool.parent_pool_id is not None:
                store.update_pool(tree.pools[pool.parent_pool_id])
            return store.delete_pool(pool_id)
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def get_mappings_by_pool(self, pool_id: int) -> list[PoolMapping]:
        """Get mappings by pool within one application transaction."""
        return self._gateway.run(lambda store: store.get_mappings_by_pool(pool_id), permission=Permission.SHARED)

    def get_all_mappings(self) -> list[PoolMapping]:
        """Get all mappings within one application transaction."""
        return self._gateway.run(lambda store: store.get_all_mappings(), permission=Permission.SHARED)

    def create_mapping(self, mapping: PoolMapping) -> int:
        """Create mapping within one application transaction."""
        mapping = normalize_mapping(mapping)
        def operation(store: ResourcePoolStore) -> int:
            PoolHierarchy(store.get_all_pools()).require_leaf(mapping.pool_id)
            return store.create_mapping(mapping)
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def update_mapping(self, mapping_id: int, allocation_pct: float) -> bool:
        """Update mapping within one application transaction."""
        validate_allocation_pct(allocation_pct)
        return self._gateway.run(lambda store: store.update_mapping(mapping_id, allocation_pct), write=True, permission=Permission.SHARED)

    def save_mappings(self, pool_id: int, mappings: list[PoolMapping]) -> None:
        """Atomically add, edit and remove a leaf pool's employee/team mappings.

        Legacy function mappings are preserved. Existing target identities retain
        their mapping IDs through the store's upsert operation.
        """
        desired = [normalize_mapping(replace(row, pool_id=pool_id, id=None)) for row in mappings]
        keys = {(row.target_type, row.target_id) for row in desired}
        if len(keys) != len(desired) or any(row.target_type not in {'employee', 'team'} for row in desired):
            raise ValueError('Select each employee or team only once.')
        def operation(store: ResourcePoolStore) -> None:
            PoolHierarchy(store.get_all_pools()).require_leaf(pool_id)
            for row in store.get_mappings_by_pool(pool_id):
                if row.target_type in {'employee', 'team'} and (row.target_type, row.target_id) not in keys:
                    store.delete_mapping(row.id)
            for row in desired:
                store.create_mapping(row)
        self._gateway.run(operation, write=True, permission=Permission.SHARED)

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
        def operation(store: ResourcePoolStore) -> int:
            PoolHierarchy(store.get_all_pools()).require_leaf(assignment.pool_id)
            return store.create_assignment(assignment)
        return self._gateway.run(operation, write=True)

    def update_assignment(self, assignment: PoolAssignment) -> bool:
        """Update assignment within one application transaction."""
        if assignment.id is None:
            return False
        assignment = normalize_assignment(assignment)
        def operation(store: ResourcePoolStore) -> bool:
            if store.get_assignment_by_id(assignment.id) is None:
                return False
            PoolHierarchy(store.get_all_pools()).require_leaf(assignment.pool_id)
            return store.update_assignment(assignment)
        return self._gateway.run(operation, write=True)

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
        """Offer only dictionary entries classified by the pool_tag group."""
        return self._gateway.run(lambda store: [tag for tag in store.get_tag_choices()
                                                if tag.tag_group_name == 'pool_tag'], permission=Permission.SHARED)

    def project_ids_for_statuses(self, statuses: list[str]) -> set[int]:
        """Select visible projects for demand; an empty selection means no demand."""
        from app.domain.projects.project import PROJECT_STATUSES
        selected = set(statuses)
        if selected - set(PROJECT_STATUSES):
            raise ValueError('Unknown project status.')
        return self._gateway.run(lambda store: {identity for identity, status in store.project_statuses().items()
                                                if status in selected})

    def get_tags_by_pools(self, pool_ids: list[int]) -> dict[int, list[str]]:
        """Batch pool-tag labels for the hierarchy without per-row queries."""
        def operation(store: ResourcePoolStore) -> dict[int, list[str]]:
            result: dict[int, list[str]] = {}
            for tag in store.get_tags_by_pools(pool_ids):
                if tag.tag_group_name == 'pool_tag':
                    result.setdefault(tag.pool_id, []).append(tag.tag_name)
            return result
        return self._gateway.run(operation, permission=Permission.SHARED)

    def get_pool_tags(self, pool_id: int) -> list[PoolTag]:
        """Get pool tags within one application transaction."""
        return self._gateway.run(lambda store: store.get_pool_tags(pool_id), permission=Permission.SHARED)

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
