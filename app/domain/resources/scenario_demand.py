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


def comparison_pool_demand(
    active_assignments: dict[int, list[CapacityAssignment]],
    alternatives: dict[int, PlanContent],
    selected_projects: set[int],
    included_projects: set[int],
) -> dict[int, dict[str, dict[str, float]]]:
    """Substitute displayed alternatives while preserving selection and status scope.

    Each project's active allocations are removed before its alternative is added,
    including when the alternative no longer allocates a previously used pool.
    """
    replacements = {pid: content for pid, content in alternatives.items() if pid in included_projects}
    total_alternative = scenario_pool_demand(replacements)
    selected_alternative = scenario_pool_demand({pid: content for pid, content in replacements.items()
                                                if pid in selected_projects})
    result = {}
    for pool_id in active_assignments.keys() | total_alternative.keys():
        retained = [row for row in active_assignments.get(pool_id, [])
                    if row['project_id'] in included_projects and row['project_id'] not in replacements]
        series = {}
        for scope, projects, alternative in [('total', None, total_alternative),
                                              ('selected', selected_projects, selected_alternative)]:
            usage = demand_timeline(retained, projects)
            for day, amount in alternative.get(pool_id, {}).items():
                usage[day] = round(usage.get(day, 0) + amount, 3)
            series[scope] = usage
        result[pool_id] = series
    return result


def changed_comparison_scopes(
    active_assignments: dict[int, list[CapacityAssignment]],
    comparison: dict[int, dict[str, dict[str, float]]],
    selected_projects: set[int],
    included_projects: set[int],
) -> dict[int, list[str]]:
    """Identify differing daily consumption, treating missing dates as zero demand."""
    changed = {}
    for pool_id, series in comparison.items():
        rows = [row for row in active_assignments.get(pool_id, []) if row['project_id'] in included_projects]
        scopes = []
        for scope, projects in [('total', None), ('selected', selected_projects)]:
            active = demand_timeline(rows, projects)
            alternative = series[scope]
            if any(abs(active.get(day, 0) - alternative.get(day, 0)) > .0001
                   for day in active.keys() | alternative.keys()):
                scopes.append(scope)
        if scopes:
            changed[pool_id] = scopes
    return changed
