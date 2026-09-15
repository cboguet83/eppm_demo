"""Date-aligned capacity and demand rollups for container pools."""

from app.domain.resources.capacity_rules import calculate_daily_overassignments, group_date_intervals
from app.domain.resources.models import PoolCapacityDetail, ResourcePool


def aggregate_capacity(pool: ResourcePool, children: list[PoolCapacityDetail]) -> PoolCapacityDetail:
    """Sum child capacity and same-day demand, preserving each leaf's demand rules.

    Args:
        pool: Container identity and label; its own capacity is ignored.
        children: Disjoint child subtrees, or the container's distinct leaf pools.

    Returns:
        A read-only rollup; no allocations or capacity values are persisted.
    """
    effective = round(sum(child.effective_capacity_fte for child in children), 3)
    assigned = round(sum(child.assigned_capacity_fte for child in children), 3)
    days = {day for child in children for day in child.capacity_calendar}
    calendar = {day: round(sum(child.capacity_calendar.get(day, child.effective_capacity_fte)
                               for child in children), 3) for day in days}
    staffing_days = {day for child in children for day in child.daily_assigned_capacity}
    staffing = {day: round(sum(child.daily_assigned_capacity.get(day, child.assigned_capacity_fte)
                               for child in children), 3) for day in staffing_days}
    usage: dict[str, float] = {}
    for child in children:
        for day, demand in child.daily_usage.items():
            usage[day] = usage.get(day, 0.0) + demand
    usage = {day: round(demand, 3) for day, demand in usage.items()}
    over = calculate_daily_overassignments(usage, effective, calendar)
    return PoolCapacityDetail(
        pool_id=pool.id, pool_name=pool.name,
        total_capacity_fte=round(sum(child.total_capacity_fte for child in children), 3),
        assigned_capacity_fte=assigned, defined_capacity_fte=None,
        effective_capacity_fte=effective, daily_effective_capacity=calendar,
        daily_assigned_capacity=staffing,
        has_assigned_resources=any(child.has_assigned_resources for child in children),
        peak_assigned_fte=max(usage.values(), default=0.0), daily_usage=usage,
        total_assigned_fte_scalar=round(sum(child.total_assigned_fte_scalar for child in children), 3),
        assignments=[assignment for child in children for assignment in child.assignments],
        contributing_resources=[],
        is_overassigned=bool(over), daily_overassignments=over,
        peak_excess_fte=max((item.excess_fte for item in over), default=0.0),
        overassignment_intervals=group_date_intervals(over),
    )
