"""Resolve plan-dependent dates and demand without combining comparison sides."""

from dataclasses import replace
from datetime import date

from app.domain.planning.plans import PlanContent
from app.domain.resources.allocation_scope import scope_pool_detail
from app.domain.resources.models import CapacityAssignment, PoolCapacityDetail
from app.domain.resources.scheduling import relative_period


def plan_assignments(project_id: int, name: str, content: PlanContent,
                     today: date) -> dict[int, list[CapacityAssignment]]:
    """Resolve explicit, relative and inherited dates against this plan's tasks."""
    tasks = {row['id']: row for row in content.tasks}
    first = min((row['start_date'] for row in content.tasks), default=today.isoformat())
    last = max((row['end_date'] for row in content.tasks), default=today.isoformat())
    result: dict[int, list[CapacityAssignment]] = {}
    for row in content.assignments:
        task = tasks.get(row.task_id)
        start, stop = (task['start_date'], task['end_date']) if task else (first, last)
        if row.schedule_anchor:
            start, stop = relative_period(start, stop, row.schedule_anchor, row.offset_days, row.duration_days)
        else:
            start, stop = row.start_date or start, row.end_date or stop
        result.setdefault(row.pool_id, []).append(CapacityAssignment(
            id=row.id or 0, project_id=project_id, project_name=name, task_id=row.task_id,
            task_name=task['task_name'] if task else '', fte_assigned=row.fte_assigned,
            start_date=start, end_date=stop, is_custom_period=bool(row.start_date or row.schedule_anchor), notes=row.notes))
    return result


def scenario_capacity(details: list[PoolCapacityDetail], plans: dict[int, PlanContent],
                      names: dict[int, str], today: date) -> list[PoolCapacityDetail]:
    """Replace selected projects' current demand while retaining shared capacity."""
    replacement: dict[int, list[CapacityAssignment]] = {}
    for project_id, content in plans.items():
        for pool_id, assignments in plan_assignments(project_id, names[project_id], content, today).items():
            replacement.setdefault(pool_id, []).extend(assignments)
    result = []
    for detail in details:
        assignments = [row for row in detail.assignments if row['project_id'] not in plans]
        assignments.extend(replacement.get(detail.pool_id, []))
        result.append(scope_pool_detail(replace(detail, assignments=assignments),
                                        {row['project_id'] for row in assignments}))
    return result


def dependency_warnings(plans: dict[int, PlanContent]) -> dict[int, list[str]]:
    """Evaluate each side independently, retaining missing-endpoint warnings."""
    tasks = {row['id']: row for content in plans.values() for row in content.tasks if row['id'] > 0}
    bounds = {identity: (min((t['start_date'] for t in content.tasks), default=None),
                         max((t['end_date'] for t in content.tasks), default=None))
              for identity, content in plans.items()}
    result: dict[int, list[str]] = {}
    for identity, content in plans.items():
        warnings = []
        local_tasks = {row['id']: row for row in content.tasks}
        for dep in content.dependencies:
            successor = local_tasks.get(dep['task_id'])
            target = (successor['start_date'], successor['end_date']) if successor else bounds[identity]
            predecessor = local_tasks.get(dep['predecessor_task_id']) or tasks.get(dep['predecessor_task_id'])
            source = ((predecessor['start_date'], predecessor['end_date']) if predecessor else
                      bounds.get(dep['predecessor_project_id'], (None, None)))
            label = successor['task_name'] if successor else 'Project'
            if not all((*source, *target)):
                warnings.append(f'{label}: predecessor unavailable in the selected plans.')
                continue
            required = date.fromisoformat(source[0 if dep['link_type'][0] == 'S' else 1]).toordinal() + dep['lag_days']
            actual = date.fromisoformat(target[0 if dep['link_type'][1] == 'S' else 1]).toordinal()
            if actual < required:
                warnings.append(f'{label}: {dep["link_type"]} dependency is not satisfied.')
        result[identity] = warnings
    return result
