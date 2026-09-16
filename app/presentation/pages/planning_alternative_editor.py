"""Contextual editors for explicitly selected, plan-owned scenario content."""

from copy import deepcopy

import streamlit as st

from app.domain.planning.plans import PlanContent, ProjectPlan
from app.domain.planning.schedule_template import TemplateStep
from app.domain.planning.rules import normalize_dependency, normalize_task
from app.presentation.components.planning_workspace import PlanningWorkspace


OPERATIONS = frozenset({'create_step_full', 'update_task_full', 'delete_step', 'manage_dependencies',
    'manage_task_tags', 'manage_task_pools', 'manage_project_pools', 'import_csv_template', 'export_csv_template',
    'update_progress'})


def selected_plan(event: dict, workspace: PlanningWorkspace) -> ProjectPlan:
    """Validate the selected plan again on every popup rerun and save."""
    from app.presentation.pages.planning_scenarios import require_edit

    if event['operation'] not in OPERATIONS:
        raise ValueError('Unknown alternative scenario action.')
    if event['operation'] in {'update_task_full', 'delete_step', 'manage_task_tags', 'manage_task_pools', 'update_progress'} and event.get('id') is None:
        raise ValueError('Select a task in the alternative scenario.')
    if event['operation'] != 'export_csv_template':
        require_edit(alternative=True)
    if st.session_state.get('planning_alternatives', {}).get(event['project_id']) != event['plan_id']:
        raise ValueError('Select this alternative scenario before editing it.')
    plan, _ = workspace.plans.comparison(event['project_id'], event['plan_id'])
    if plan.revision != event['revision']:
        raise ValueError('The plan changed. Close this popup and reopen it before saving.')
    if event.get('id') is not None and not any(task['id'] == event['id'] for task in plan.content.tasks):
        raise ValueError('The task is not part of the selected scenario.')
    return plan


def _apply_step_fields(content: PlanContent, event: dict) -> None:
    """Decode the shared Gantt editor into one scenario's task and incoming links."""
    task_id = event.get('id', -1)
    values = normalize_task(event)
    values.pop('predecessor_id', None)
    task = dict(id=task_id, **values)
    if event['operation'] == 'create_step_full':
        content.tasks.append(task)
    else:
        content.tasks = [task if row['id'] == task_id else row for row in content.tasks]
    dependencies = []
    for row in event.get('dependencies', []):
        dep = normalize_dependency(task_id, row)
        if dep:
            if dep['predecessor_task_id'] is not None:
                dep['predecessor_project_id'] = None
            dependencies.append(dict(task_id=task_id, **dep))
    content.dependencies = [row for row in content.dependencies if row['task_id'] != task_id] + dependencies


def handle_alternative_action(event: dict, workspace: PlanningWorkspace) -> None:
    """Apply shared step commands or open an editor for the selected scenario."""
    plan = selected_plan(event, workspace)
    if event['operation'] in {'create_step_full', 'update_task_full', 'delete_step', 'update_progress', 'manage_dependencies'}:
        content = deepcopy(plan.content)
        if event['operation'] in {'create_step_full', 'update_task_full'}:
            _apply_step_fields(content, event)
        elif event['operation'] == 'delete_step':
            content.tasks = [task for task in content.tasks if task['id'] != event['id']]
        elif event['operation'] == 'manage_dependencies':
            dependencies = []
            for row in event.get('dependencies', []):
                dep = normalize_dependency(-1, row)
                if dep:
                    if dep['predecessor_task_id'] is not None:
                        dep['predecessor_project_id'] = None
                    dependencies.append(dict(task_id=None, **dep))
            content.dependencies = [row for row in content.dependencies if row['task_id'] is not None] + dependencies
        else:
            next(task for task in content.tasks if task['id'] == event['id'])['progress_pct'] = 100
        workspace.plans.update_alternative(plan.project_id, plan.id, plan.revision, content)
        st.toast('Alternative scenario updated.')
    else:
        st.session_state['planning_alternative_editor'] = event
    st.session_state['planning_scenario_epoch'] = st.session_state.get('planning_scenario_epoch', 0) + 1


def save_task_tag(event: dict, workspace: PlanningWorkspace, tag: dict | None = None,
                  *, delete_index: int | None = None) -> None:
    """Apply the shared tag form to one revision-checked scenario task."""
    plan = selected_plan(event, workspace)
    content = deepcopy(plan.content)
    rows = content.task_tags.setdefault(event['id'], [])
    if delete_index is not None:
        if not 0 <= delete_index < len(rows):
            raise ValueError('The selected task tag no longer exists.')
        rows.pop(delete_index)
    elif tag is not None:
        rows.append(tag)
    workspace.plans.update_alternative(plan.project_id, plan.id, plan.revision, content)


def template_content(steps: list[TemplateStep]) -> PlanContent:
    """Adapt the shared CSV preview into a new revision with fresh task identities."""
    content = PlanContent()
    for step in steps:
        content.tasks.append(dict(id=-step.number, progress_pct=step.values.get('progress_pct', 0),
            **{key: step.values.get(key, '') for key in ['task_name', 'phase', 'start_date', 'end_date', 'description']}))
        for dep in step.dependencies:
            content.dependencies.append(dict(task_id=-step.number,
                predecessor_task_id=-dep.identity if dep.kind == 'step' else dep.identity if dep.kind == 'task' else None,
                predecessor_project_id=dep.identity if dep.kind == 'project' else None,
                link_type=dep.link_type, lag_days=dep.lag_days))
    return content
