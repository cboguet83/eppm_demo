"""Resource-pool input normalization and numeric validation."""

from dataclasses import replace
from math import isfinite

from app.domain.hierarchy import validate_hierarchy_type_id
from app.domain.resources.models import (
    PoolAssignment,
    PoolMapping,
    ResourcePool,
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
    validate_hierarchy_type_id(pool.hierarchy_type_id)
    if type(pool.pool_type_id) is not int or pool.pool_type_id <= 0:
        raise ValueError("A valid pool type is required.")
    validate_pool_name(pool.name)
    if pool.capacity_fte is not None:
        validate_capacity_fte(pool.capacity_fte)
    return replace(pool, name=pool.name.strip(), description=pool.description.strip())


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
    relative = (assignment.schedule_anchor, assignment.offset_days, assignment.duration_days)
    if any(value is not None for value in relative):
        if assignment.schedule_anchor not in {"start", "end"}:
            raise ValueError("Select the start or end as the schedule anchor.")
        if type(assignment.offset_days) is not int or not -9124 <= assignment.offset_days <= 9124:
            raise ValueError("Offset must be an integer between -9124 and 9124 calendar days.")
        if type(assignment.duration_days) is not int or not 1 <= assignment.duration_days <= 9125:
            raise ValueError("Duration must be an integer between 1 and 9125 calendar days.")
        if assignment.start_date is not None or assignment.end_date is not None:
            raise ValueError("Relative assignments cannot also store fixed dates.")
    return replace(assignment, notes=assignment.notes.strip())
