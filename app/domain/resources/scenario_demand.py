"""Resolve scenario allocations using the shared daily demand rules."""

from collections import defaultdict

from app.domain.planning.plans import PlanContent
from app.domain.resources.models import CapacityAssignment
from app.domain.resources.scheduling import relative_period
from app.domain.resources.timeline import demand_timeline


def scenario_pool_demand(contents: dict[int, PlanContent]) -> dict[int, dict[str, float]]:
    """Calculate selected alternatives independently of active portfolio demand."""
    pools: dict[int, list[CapacityAssignment]] = defaultdict(list)
    for project_id, content in contents.items():
        tasks = {task['id']: task for task in content.tasks}
        project_start = min((task['start_date'] for task in content.tasks), default=None)
        project_end = max((task['end_date'] for task in content.tasks), default=None)
        for assignment in content.assignments:
            task = tasks.get(assignment.task_id)
            start = task['start_date'] if task else project_start
            end = task['end_date'] if task else project_end
            first, last = assignment.start_date or start, assignment.end_date or end
            if assignment.schedule_anchor and start and end:
                first, last = relative_period(start, end, assignment.schedule_anchor,
                                              assignment.offset_days, assignment.duration_days)
            if not first or not last:
                continue
            pools[assignment.pool_id].append(CapacityAssignment(
                id=assignment.id, project_id=project_id, project_name='',
                task_id=assignment.task_id, task_name='', fte_assigned=assignment.fte_assigned,
                start_date=first, end_date=last, is_custom_period=bool(assignment.start_date), notes=''))
    return {identity: demand_timeline(rows) for identity, rows in pools.items()}
