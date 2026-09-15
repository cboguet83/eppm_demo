"""Identify projects consuming capacity on an actually overloaded day."""

from bisect import bisect_left
from collections.abc import Sequence, Set
from dataclasses import dataclass, replace
from datetime import date

from app.domain.resources.models import PoolCapacityDetail


@dataclass(frozen=True)
class OverallocationPeriod:
    """Inclusive consecutive dates with a constant excess FTE for one pool."""

    pool_name: str
    start_date: date
    stop_date: date
    fte: float


def overallocation_periods(pools: Sequence[PoolCapacityDetail]) -> list[OverallocationPeriod]:
    """Group each pool's overloaded days, splitting at gaps or excess changes."""
    periods: list[OverallocationPeriod] = []
    for pool in sorted(pools, key=lambda item: (item.pool_name.casefold(), item.pool_id)):
        current: OverallocationPeriod | None = None
        for day in sorted(pool.daily_overassignments, key=lambda item: item.date):
            day_date = date.fromisoformat(day.date)
            if (current is not None and (day_date - current.stop_date).days == 1
                    and day.excess_fte == current.fte):
                current = replace(current, stop_date=day_date)
                periods[-1] = current
            else:
                current = OverallocationPeriod(pool.pool_name, day_date, day_date, day.excess_fte)
                periods.append(current)
    return periods


def overloaded_consumers(pools: Sequence[PoolCapacityDetail], requested: Set[int]) -> set[int]:
    """Find positive project/task demand intersecting a pool's daily overloads.

    Capacity rules already resolve task dates, staffing, employee deduplication,
    calendar exceptions, and unstaffed-pool fallback. This rule only intersects
    their resulting dates with assignments for the requested portfolio page.
    """
    result: set[int] = set()
    for pool in pools:
        days = sorted(item.date for item in pool.daily_overassignments)
        for assignment in pool.assignments:
            project_id = int(assignment["project_id"])
            if (
                project_id not in requested
                or project_id in result
                or float(assignment["fte_assigned"]) <= 0
            ):
                continue
            start, end = assignment.get("start_date"), assignment.get("end_date")
            if not start or not end:
                continue
            index = bisect_left(days, str(start))
            if index < len(days) and days[index] <= str(end):
                result.add(project_id)
    return result


def assignment_is_overallocated(
    fte: float,
    start_date: str,
    end_date: str,
    pool: PoolCapacityDetail,
) -> bool:
    """Keep the planner's individual-demand and overlapping-day warning rule."""
    return fte > pool.total_capacity_fte + 1e-4 or any(
        start_date <= day.date <= end_date for day in pool.daily_overassignments
    )
