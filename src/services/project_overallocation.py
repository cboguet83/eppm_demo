"""Find projects participating in pool overloads using the cached daily results."""

from bisect import bisect_left
from contextlib import closing
import json

from src.database.connection import get_db
from src.services.pool_capacity_cache import load_pool_capacities


def overallocated_project_ids(db_path: str | None, project_ids: list[int]) -> set[int]:
    """Return page projects consuming capacity on at least one overloaded day.

    Args:
        db_path: Application database path.
        project_ids: Only the projects in the requested portfolio page.

    Returns:
        IDs whose positive project/task assignment overlaps an actual overload.
        Capacity calculation, employee deduplication and calendar exceptions are
        delegated to the shared pool cache, including unstaffed-pool fallback.
    """
    requested = set(project_ids)
    if not requested:
        return set()
    with closing(get_db(db_path)) as conn:
        pool_ids = [row[0] for row in conn.execute("""SELECT DISTINCT pool_id
            FROM resource_pool_assignment WHERE fte_assigned > 0
            AND project_id IN (SELECT value FROM json_each(?))""", (json.dumps(sorted(requested)),))]
    if not pool_ids:
        return set()
    summaries = load_pool_capacities(db_path, pool_ids=pool_ids)
    overloaded = [pool.pool_id for pool in summaries if pool.is_overassigned]
    if not overloaded:
        return set()
    result: set[int] = set()
    for pool in load_pool_capacities(db_path, details=True, pool_ids=overloaded):
        days = sorted(item.date for item in pool.daily_overassignments)
        for assignment in pool.assignments:
            project_id = int(assignment["project_id"])
            if project_id not in requested or project_id in result or float(assignment["fte_assigned"]) <= 0:
                continue
            start, end = assignment.get("start_date"), assignment.get("end_date")
            if not start or not end:
                continue
            index = bisect_left(days, str(start))
            if index < len(days) and days[index] <= str(end):
                result.add(project_id)
    return result
