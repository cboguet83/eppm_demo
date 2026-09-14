"""Project and inclusive-period scopes for resource demand projections."""

from dataclasses import replace
from datetime import date

from app.domain.resources.capacity_rules import calculate_daily_overassignments, group_date_intervals
from app.domain.resources.models import CapacityAssignment, PoolCapacityDetail
from app.domain.resources.timeline import demand_timeline


def scoped_assignments(assignments: list[CapacityAssignment], project_ids: set[int] | None = None,
                       start: str | None = None, end: str | None = None) -> list[CapacityAssignment]:
    """Keep positive assignments overlapping an inclusive period and project set."""
    first = date.fromisoformat(start) if start else date.min
    last = date.fromisoformat(end) if end else date.max
    if last < first:
        raise ValueError('The allocation period must end on or after its start.')
    return [row for row in assignments if row['fte_assigned'] > 0
            and (project_ids is None or row['project_id'] in project_ids)
            and row['start_date'] <= last.isoformat() and row['end_date'] >= first.isoformat()]


def scope_pool_detail(detail: PoolCapacityDetail, project_ids: set[int]) -> PoolCapacityDetail:
    """Recalculate demand summaries for a project set without changing capacity."""
    assignments = scoped_assignments(detail.assignments, project_ids)
    usage = demand_timeline(assignments)
    over = calculate_daily_overassignments(usage, detail.effective_capacity_fte, detail.capacity_calendar)
    scalar: dict[int, list[float]] = {}
    for row in assignments:
        values = scalar.setdefault(row['project_id'], [0.0, 0.0])
        values[int(row['task_id'] is not None)] += row['fte_assigned']
    return replace(detail, assignments=assignments, daily_usage=usage,
                   peak_assigned_fte=round(max(usage.values(), default=0), 3),
                   total_assigned_fte_scalar=round(sum(max(values) for values in scalar.values()), 3),
                   is_overassigned=bool(over), daily_overassignments=over,
                   peak_excess_fte=round(max((item.excess_fte for item in over), default=0), 3),
                   overassignment_intervals=group_date_intervals(over))
