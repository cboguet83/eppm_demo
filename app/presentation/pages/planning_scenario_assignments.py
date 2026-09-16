"""Scenario data adapters for the existing task and project resource dialogs."""

from copy import deepcopy

from app.domain.planning.plans import ProjectPlan
from app.domain.resources.models import AssignmentRow, PoolAssignment
from app.domain.resources.scheduling import relative_period
from app.presentation.components.planning_workspace import PlanningWorkspace
from app.presentation.pages.planning_alternative_editor import selected_plan


def assignment_rows(plan: ProjectPlan, task_id: int | None,
                    pool_names: dict[int, str]) -> tuple[tuple[str | None, str | None], list[AssignmentRow]]:
    """Format selected scenario allocations with dates from that scenario only."""
    tasks = [row for row in plan.content.tasks if task_id is None or row['id'] == task_id]
    start = min((row['start_date'] for row in tasks), default=None)
    end = max((row['end_date'] for row in tasks), default=None)
    rows = []
    for assignment in plan.content.assignments:
        if assignment.task_id != task_id:
            continue
        first, last = assignment.start_date or start, assignment.end_date or end
        if assignment.schedule_anchor and start and end:
            first, last = relative_period(start, end, assignment.schedule_anchor,
                                          assignment.offset_days, assignment.duration_days)
        rows.append(AssignmentRow(id=assignment.id, pool_id=assignment.pool_id,
            pool_name=pool_names.get(assignment.pool_id, str(assignment.pool_id)),
            project_id=plan.project_id, project_name='', task_id=task_id,
            task_name=tasks[0]['task_name'] if task_id is not None else None,
            task_start_date=start, task_end_date=end, fte_assigned=assignment.fte_assigned,
            custom_start_date=assignment.start_date, custom_end_date=assignment.end_date,
            effective_start_date=first, effective_end_date=last, notes=assignment.notes,
            schedule_anchor=assignment.schedule_anchor, offset_days=assignment.offset_days,
            duration_days=assignment.duration_days))
    return (start, end), rows


def save_assignment(event: dict | None, workspace: PlanningWorkspace,
                    assignment: PoolAssignment | None = None, *, delete_id: int | None = None) -> None:
    """Route the shared form to its selected plan with revision checks on save."""
    if event is None:
        if delete_id is not None:
            if not workspace.resources.delete_assignment(delete_id):
                raise ValueError('The resource assignment no longer exists.')
        else:
            workspace.resources.create_assignment(assignment)
        return
    plan = selected_plan(event, workspace)
    content = deepcopy(plan.content)
    task_id = event.get('id')
    if delete_id is not None:
        if not any(row.id == delete_id and row.task_id == task_id for row in content.assignments):
            raise ValueError('The resource assignment is not part of this scenario step.')
        content.assignments = [row for row in content.assignments if row.id != delete_id]
    else:
        if assignment is None or assignment.project_id != plan.project_id or assignment.task_id != task_id:
            raise ValueError('The resource assignment must target the selected scenario step.')
        content.assignments.append(assignment)
    workspace.plans.update_alternative(plan.project_id, plan.id, plan.revision, content)
