"""Pure daily-capacity evaluation and interval display rules."""

import datetime

from app.domain.resources.models import (
    CapacityAssignment,
    DailyOverassignment,
    PoolCapacityDetail,
    ProjectPoolStatus,
)
from app.domain.resources.timeline import demand_timeline


def get_effective_capacity_for_date(
    date_str: str,
    base_capacity_fte: float,
    daily_capacity: dict[str, float] | None = None,
) -> float:
    """Return the effective capacity for one date, honoring sparse overrides."""
    if daily_capacity and date_str in daily_capacity:
        return round(float(daily_capacity[date_str]), 3)
    return round(float(base_capacity_fte), 3)


def calculate_daily_overassignments(
    daily_usage: dict[str, float],
    base_capacity_fte: float,
    daily_capacity: dict[str, float] | None = None,
) -> list[DailyOverassignment]:
    """Compare every demand day with that day's effective capacity.

    A period is therefore considered overallocated when even a single day
    exceeds capacity; an otherwise under-capacity period cannot hide it.
    """
    overassignments: list[DailyOverassignment] = []
    for date_str in sorted(daily_usage):
        demand_fte = round(float(daily_usage[date_str]), 3)
        capacity_fte = get_effective_capacity_for_date(date_str, base_capacity_fte, daily_capacity)
        if demand_fte > capacity_fte + 1e-4:
            overassignments.append(
                DailyOverassignment(
                    date=date_str,
                    capacity_fte=capacity_fte,
                    assigned_fte=demand_fte,
                    excess_fte=round(demand_fte - capacity_fte, 3),
                )
            )
    return overassignments


def accumulate_daily_usage(
    daily_map: dict[str, float],
    start_str: str,
    end_str: str,
    fte: float,
) -> None:
    """Accumulates FTE into daily map for each calendar date between start and end inclusive.

    Args:
        daily_map: Dictionary mapping YYYY-MM-DD to cumulative FTE.
        start_str: Start date string (YYYY-MM-DD).
        end_str: End date string (YYYY-MM-DD).
        fte: FTE amount to add.
    """
    try:
        d_start = datetime.date.fromisoformat(start_str.strip()[:10])
        d_end = datetime.date.fromisoformat(end_str.strip()[:10])
    except ValueError, TypeError:
        return

    if d_end < d_start:
        d_end = d_start

    # Cap span to 25 years max for memory and boundary safety
    curr = d_start
    delta = datetime.timedelta(days=1)
    max_days = 365 * 25
    count = 0
    while curr <= d_end and count < max_days:
        k = curr.isoformat()
        daily_map[k] = daily_map.get(k, 0.0) + fte
        curr += delta
        count += 1


def group_date_intervals(daily_overassignments: list[DailyOverassignment]) -> list[str]:
    """Groups consecutive daily overassignment records into human-readable interval strings.

    Args:
        daily_overassignments: List of DailyOverassignment instances.

    Returns:
        list[str]: Formatted interval strings (e.g. '2026-02-16 to 2026-03-01 (+1.50 FTE)').
    """
    if not daily_overassignments:
        return []

    intervals: list[str] = []
    start_d = daily_overassignments[0].date
    prev_d = start_d
    max_excess = daily_overassignments[0].excess_fte

    delta = datetime.timedelta(days=1)

    for rec in daily_overassignments[1:]:
        try:
            curr_date = datetime.date.fromisoformat(rec.date)
            prev_date = datetime.date.fromisoformat(prev_d)
        except ValueError:
            continue

        if curr_date == prev_date + delta:
            prev_d = rec.date
            max_excess = max(max_excess, rec.excess_fte)
        else:
            if start_d == prev_d:
                intervals.append(f"{start_d} (+{max_excess:.2f} FTE)")
            else:
                intervals.append(f"{start_d} to {prev_d} (+{max_excess:.2f} FTE)")
            start_d = rec.date
            prev_d = rec.date
            max_excess = rec.excess_fte

    if start_d == prev_d:
        intervals.append(f"{start_d} (+{max_excess:.2f} FTE)")
    else:
        intervals.append(f"{start_d} to {prev_d} (+{max_excess:.2f} FTE)")

    return intervals


def calculate_pool_scope_daily_usage(
    assignments: list[CapacityAssignment],
    project_ids: list[int | str],
) -> dict[str, float]:
    """Calculates deduplicated daily usage for a pool restricted to a given list of project IDs.

    Args:
        assignments: List of assignment dicts with project_id, task_id, start_date, end_date, fte_assigned.
        project_ids: Filter list of project IDs.

    Returns:
        dict[str, float]: Deduplicated daily usage mapping date_str -> fte.
    """
    return demand_timeline(assignments, project_ids)


def get_projects_consuming_pool_in_period(
    assignments: list[CapacityAssignment],
    start_date: str,
    end_date: str,
) -> list[int]:
    """Identifies all project IDs that consume a pool during a specified date range.

    Args:
        assignments: List of pool assignment records.
        start_date: Period start date (YYYY-MM-DD).
        end_date: Period end date (YYYY-MM-DD).

    Returns:
        list[int]: Unique sorted list of project IDs consuming the pool in that period.
    """
    matching_pids: set[int] = set()
    s_date = str(start_date).strip()[:10]
    e_date = str(end_date).strip()[:10]
    if not s_date or not e_date:
        return []

    for a in assignments:
        a_start = str(a.get("start_date", "")).strip()[:10]
        a_end = str(a.get("end_date", "")).strip()[:10]
        if not a_start or not a_end:
            continue
        if float(a.get("fte_assigned", 0.0)) <= 0:
            continue
        p_id = int(a["project_id"])
        # Overlap condition: a_start <= e_date and a_end >= s_date
        if a_start <= e_date and a_end >= s_date:
            matching_pids.add(p_id)

    return sorted(list(matching_pids))


def project_pool_status(project_id: int, detail: PoolCapacityDetail) -> ProjectPoolStatus:
    """Evaluate one project's deduplicated demand against dated pool capacity."""
    assignments = [row for row in detail.assignments if row["project_id"] == project_id]
    usage = demand_timeline(assignments)
    capacity = detail.daily_assigned_capacity if detail.has_assigned_resources else None
    over = calculate_daily_overassignments(usage, detail.effective_capacity_fte, capacity)
    return ProjectPoolStatus(
        pool_id=detail.pool_id,
        pool_name=detail.pool_name,
        pool_capacity_fte=detail.effective_capacity_fte,
        minimum_capacity_fte=min(
            (
                get_effective_capacity_for_date(day, detail.effective_capacity_fte, capacity)
                for day in usage
            ),
            default=detail.effective_capacity_fte,
        ),
        project_peak_assigned_fte=round(max(usage.values(), default=0.0), 3),
        is_overassigned=bool(over),
        excess_fte=max((item.excess_fte for item in over), default=0.0),
        overallocated_dates=[item.date for item in over],
        assignments_count=len(assignments),
    )
