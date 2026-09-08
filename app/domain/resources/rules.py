"""Resource-pool input rules and cycle-safe group traversal."""

from dataclasses import replace
from math import isfinite

from app.domain.resources.models import (
    PoolAssignment,
    PoolMapping,
    ResourcePool,
    ResourcePoolGroup,
    ResourcePoolGroupMember,
)


def validate_pool_name(name: str) -> None:
    """Validates that a resource pool name is non-empty.

    Args:
        name: Resource pool name to validate.

    Raises:
        ValueError: If name is empty or whitespace.
    """
    if not name or not name.strip():
        raise ValueError("Resource pool name cannot be empty.")


def validate_allocation_pct(allocation_pct: float) -> None:
    """Validates that a mapping allocation percentage is between 0.0 and 100.0.

    Args:
        allocation_pct: Percentage value to test.

    Raises:
        ValueError: If percentage is outside [0.0, 100.0].
    """
    if not isfinite(allocation_pct) or not 0 <= allocation_pct <= 100:
        raise ValueError(
            f"Allocation percentage must be between 0.0 and 100.0 (got {allocation_pct})."
        )


def validate_fte(fte: float) -> None:
    """Validates that an assigned FTE value is non-negative.

    Args:
        fte: FTE value to test.

    Raises:
        ValueError: If FTE is negative.
    """
    if not isfinite(fte) or fte < 0:
        raise ValueError(f"Assigned FTE must be greater than or equal to 0.0 (got {fte}).")


def validate_capacity_fte(capacity_fte: float) -> None:
    """Validate a user-defined pool capacity limit."""
    if not isfinite(capacity_fte) or capacity_fte < 0:
        raise ValueError(
            f"Pool capacity must be greater than or equal to 0.0 (got {capacity_fte})."
        )


def normalize_pool(pool: ResourcePool) -> ResourcePool:
    """Validate pool capacity while preserving the unspecified-capacity fallback."""
    validate_pool_name(pool.name)
    if pool.capacity_fte is not None:
        validate_capacity_fte(pool.capacity_fte)
    return replace(pool, name=pool.name.strip(), description=pool.description.strip())


def normalize_group(group: ResourcePoolGroup) -> ResourcePoolGroup:
    """Require a group name without changing its identity."""
    if not group.name.strip():
        raise ValueError("Pool group name is required.")
    return replace(group, name=group.name.strip(), description=group.description.strip())


def normalize_mapping(mapping: PoolMapping) -> PoolMapping:
    """Normalize the existing mapping kinds and validate its allocation."""
    target = mapping.target_type.strip().lower()
    if target not in {"team", "employee", "function"}:
        raise ValueError("Mapping target must be a team, employee, or function.")
    validate_allocation_pct(mapping.allocation_pct)
    return replace(mapping, target_type=target)


def normalize_assignment(assignment: PoolAssignment) -> PoolAssignment:
    """Validate demand and trim notes; retain legacy date resolution rules."""
    validate_fte(assignment.fte_assigned)
    return replace(assignment, notes=assignment.notes.strip())


def descendant_groups(group_id: int, members: list[ResourcePoolGroupMember]) -> set[int]:
    """Resolve groups once, terminating even on legacy cyclic input."""
    children: dict[int, set[int]] = {}
    for member in members:
        if member.child_group_id is not None:
            children.setdefault(member.group_id, set()).add(member.child_group_id)
    pending, visited = [group_id], set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(children.get(current, set()) - visited)
    return visited


def descendant_pools(group_id: int, members: list[ResourcePoolGroupMember]) -> list[int]:
    """Deduplicate pools reached through multiple branches of a group graph."""
    groups = descendant_groups(group_id, members)
    return sorted(
        {
            member.pool_id
            for member in members
            if member.group_id in groups and member.pool_id is not None
        }
    )


def validate_group_children(
    group_id: int,
    child_ids: list[int],
    members: list[ResourcePoolGroupMember],
) -> None:
    """Reject proposed edges that make the current group reachable from a child."""
    for child_id in child_ids:
        if group_id in descendant_groups(child_id, members):
            raise ValueError(
                f"Adding pool group #{child_id} below #{group_id} would create a loop."
            )
