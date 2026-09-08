"""Identify projects consuming capacity on an actually overloaded day."""

from bisect import bisect_left
from collections.abc import Sequence, Set

from app.domain.resources.models import PoolCapacityDetail


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
