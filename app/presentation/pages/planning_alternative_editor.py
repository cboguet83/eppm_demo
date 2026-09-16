"""Contextual editors for explicitly selected, plan-owned scenario content."""

from copy import deepcopy

import pandas as pd
import streamlit as st

from app.application.exceptions import PlanningStorageError
from app.domain.planning.plans import PlanContent, ProjectPlan
from app.domain.planning.schedule_template import export_template, parse_template
from app.domain.planning.rules import normalize_dependency, normalize_task
from app.presentation.components.dialog import dialog
from app.presentation.components.planning_workspace import PlanningWorkspace
from app.presentation.pages.project_plans import _dependency_editor


OPERATIONS = frozenset({'create_step_full', 'update_task_full', 'delete_step', 'manage_dependencies',
    'manage_task_tags', 'manage_task_pools', 'manage_project_pools', 'import_csv_template', 'export_csv_template',
    'update_progress', 'view_project_details'})


def selected_plan(event: dict, workspace: PlanningWorkspace) -> ProjectPlan:
    """Validate the selected plan again on every popup rerun and save."""
    from app.presentation.pages.planning_scenarios import require_edit

    if event['operation'] not in OPERATIONS:
        raise ValueError('Unknown alternative scenario action.')
    if event['operation'] in {'update_task_full', 'delete_step', 'manage_task_tags', 'manage_task_pools', 'update_progress'} and event.get('id') is None:
        raise ValueError('Select a task in the alternative scenario.')
    if event['operation'] not in {'export_csv_template', 'view_project_details'}:
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
    if event['operation'] in {'create_step_full', 'update_task_full', 'delete_step', 'update_progress'}:
        content = deepcopy(plan.content)
        if event['operation'] in {'create_step_full', 'update_task_full'}:
            _apply_step_fields(content, event)
        elif event['operation'] == 'delete_step':
            content.tasks = [task for task in content.tasks if task['id'] != event['id']]
        else:
            next(task for task in content.tasks if task['id'] == event['id'])['progress_pct'] = 100
        workspace.plans.update_alternative(plan.project_id, plan.id, plan.revision, content)
        st.toast('Alternative scenario updated.')
    else:
        st.session_state['planning_alternative_editor'] = event
    st.session_state['planning_scenario_epoch'] = st.session_state.get('planning_scenario_epoch', 0) + 1


def _dependencies(content: PlanContent, draft: dict, project_id: int, task_id: int | None,
                  workspace: PlanningWorkspace) -> list[dict]:
    """Edit only incoming links of the contextual task or project."""
    draft['base'].dependencies = [row for row in content.dependencies if row['task_id'] == task_id]
    projects = {row['id']: row['name'] for row in workspace.projects.projects.get_planning_catalog()}
    external = {row['id']: f"{row['project_name']}: {row['task_name']} (#{row['id']})"
                for row in workspace.plans.task_choices() if row['project_id'] != project_id}
    rows = _dependency_editor(project_id, draft, content.tasks, projects, external,
                              fixed_successor=True, successor_id=task_id)
    if any(row['task_id'] != task_id for row in rows):
        raise ValueError('Keep the successor set to this step (or empty for project dependencies).')
    return [row for row in content.dependencies if row['task_id'] != task_id] + rows


def _tags(content: PlanContent, task_id: int, workspace: PlanningWorkspace, key: str) -> None:
    choices = workspace.plans.tag_choices()
    labels = {identity: f'{name} (#{identity})' for identity, name in choices.items()}
    frame = pd.DataFrame([dict(Tag=labels.get(row['tag_id']), Text=row['free_tag'])
                          for row in content.task_tags.get(task_id, [])], columns=['Tag', 'Text'])
    edited = st.data_editor(frame, hide_index=True, num_rows='dynamic', width='stretch', key=key,
        column_config={'Tag': st.column_config.SelectboxColumn(options=list(labels.values())), 'Text': 'Free text'})
    identities = {label: identity for identity, label in labels.items()}
    content.task_tags[task_id] = [dict(tag_id=identities.get(row['Tag']),
        free_tag=row['Text'] if pd.notna(row['Text']) else None) for row in edited.to_dict('records')]


def _import_csv() -> PlanContent | None:
    st.caption('Import replaces the alternative’s tasks. Replaced tasks release their resource assignments.')
    upload = st.file_uploader('CSV template', type=['csv'])
    if upload is None:
        return None
    content = PlanContent()
    for step in parse_template(upload.getvalue().decode('utf-8-sig')):
        content.tasks.append(dict(id=-step.number, progress_pct=step.values.get('progress_pct', 0),
            **{key: step.values.get(key, '') for key in ['task_name', 'phase', 'start_date', 'end_date', 'description']}))
        for dep in step.dependencies:
            content.dependencies.append(dict(task_id=-step.number,
                predecessor_task_id=-dep.identity if dep.kind == 'step' else dep.identity if dep.kind == 'task' else None,
                predecessor_project_id=dep.identity if dep.kind == 'project' else None,
                link_type=dep.link_type, lag_days=dep.lag_days))
    return content


@dialog('Edit alternative scenario', width='large')
def edit_alternative(event: dict, workspace: PlanningWorkspace) -> None:
    """Expose contextual scenario fields without passing alternative IDs to live services."""
    try:
        plan = selected_plan(event, workspace)
        st.caption(f'{plan.name} · v{plan.version}')
        operation, task_id = event['operation'], event.get('id')
        if operation == 'view_project_details':
            row = next(row for row in workspace.projects.projects.get_planning_catalog() if row['id'] == plan.project_id)
            st.dataframe(pd.DataFrame([row]), hide_index=True)
            return
        content = deepcopy(plan.content)
        if operation == 'export_csv_template':
            st.download_button('Download alternative CSV', export_template(content.tasks, content.dependencies),
                file_name=f'project_{plan.project_id}_plan_{plan.id}.csv', mime='text/csv')
            return
        draft = dict(base=deepcopy(content), epoch=f'alternative_{plan.id}_{plan.revision}_{operation}_{task_id}')
        if operation == 'manage_dependencies':
            content.dependencies = _dependencies(content, draft, plan.project_id, None, workspace)
        elif operation == 'manage_task_tags':
            _tags(content, task_id, workspace, draft['epoch'])
        elif operation == 'import_csv_template':
            content = _import_csv()
        if st.button('Save alternative', type='primary', disabled=content is None):
            selected_plan(event, workspace)
            workspace.plans.update_alternative(plan.project_id, plan.id, event['revision'], content)
            st.session_state['planning_scenario_epoch'] = st.session_state.get('planning_scenario_epoch', 0) + 1
            st.toast('Alternative scenario saved.')
            st.rerun()
    except (ValueError, PlanningStorageError) as error:
        st.error(str(error))
