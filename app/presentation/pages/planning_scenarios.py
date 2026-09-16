"""Session-owned Gantt edit mode and explicit alternative scenario selection."""

from typing import Any

import streamlit as st

from app.application.exceptions import PlanningStorageError
from app.domain.access.models import Permission
from app.presentation.components.dialog import dialog
from app.presentation.components.planning_workspace import PlanningWorkspace


SCENARIO_ACTIONS = frozenset({'toggle_edit', 'toggle_baseline', 'baseline_current_project',
                              'delete_project_baseline', 'choose_alternative', 'update_alternative_dates',
                              'hide_alternatives', 'activate_alternative', 'alternative_action'})
MUTATIONS = frozenset({'update_dates', 'update_progress', 'create_step_full', 'update_task_full',
                       'delete_step', 'save_project_dependencies', 'import_csv_template',
                       'manage_task_tags', 'manage_task_pools', 'manage_project_tags',
                       'manage_project_pools'})


def require_edit(*, alternative: bool = False) -> None:
    """Reject stale or forged Gantt edits before invoking application services."""
    if not st.session_state.get('planning_edit_enabled', False):
        raise ValueError('Enable edit mode before changing the schedule.')
    if not alternative and st.session_state.get('planning_alternatives'):
        raise ValueError('Only the displayed alternative scenario can be edited during comparison.')


def handle_scenario_event(event: dict[str, Any], workspace: PlanningWorkspace) -> None:
    """Route validated component JSON; authorization remains in Python services."""
    action = event['action']
    if action == 'alternative_action':
        from app.presentation.pages.planning_alternative_editor import handle_alternative_action

        handle_alternative_action(event, workspace)
        return
    if action == 'hide_alternatives':
        st.session_state['planning_alternatives'] = {}
        return
    if action == 'toggle_edit':
        st.session_state['planning_edit_enabled'] = event['enabled']
        return
    if action == 'toggle_baseline':
        st.session_state['planning_show_baseline'] = event['enabled']
        if event['enabled']:
            st.session_state['planning_alternatives'] = {}
        return
    if action == 'choose_alternative':
        st.session_state['planning_scenario_dialog_project'] = event['project_id']
        return
    if workspace.plans is None:
        return
    require_edit(alternative=action in {'update_alternative_dates', 'activate_alternative'})
    if action == 'activate_alternative':
        selected = st.session_state.get('planning_alternatives', {})
        if selected.get(event['project_id']) != event['plan_id']:
            raise ValueError('Select this alternative scenario before activating it.')
        workspace.plans.activate_alternative(event['project_id'], event['plan_id'], event['revision'])
        st.session_state['planning_alternatives'] = {}
        st.session_state.pop('planning_chart_snapshot', None)
        st.session_state.pop('planning_pending_change', None)
        st.toast('Alternative scenario is now the active plan.')
        return
    if action == 'baseline_current_project':
        workspace.plans.baseline_current(event['project_id'])
        st.toast('Current project plan set as baseline.')
    elif action == 'delete_project_baseline':
        workspace.plans.delete_baseline(event['project_id'])
        st.toast('Baseline deleted. Its history is retained.')
    elif action == 'update_alternative_dates':
        selected = st.session_state.get('planning_alternatives', {})
        if selected.get(event['project_id']) != event['plan_id']:
            raise ValueError('Select this alternative scenario before editing it.')
        try:
            workspace.plans.reschedule_alternative(event['project_id'], event['plan_id'], event['revision'],
                event['id'], event['start_date'], event['end_date'])
        finally:
            # Repaint from persisted dates after both success and a stale edit.
            st.session_state['planning_scenario_epoch'] = st.session_state.get('planning_scenario_epoch', 0) + 1
        st.toast('Alternative scenario dates updated.')


@dialog('Display an alternative scenario')
def choose_alternative(project_id: int, workspace: PlanningWorkspace) -> None:
    """Select one non-baseline alternative for the contextual project."""
    if workspace.plans is None:
        return
    try:
        plans = [plan for plan in workspace.plans.list_plans(project_id)
                 if not plan.is_current and not plan.is_baseline and not plan.is_frozen and plan.status != 'deleted']
        by_id = {plan.id: plan for plan in plans}
        if not plans:
            st.info('No alternative scenario is available. Create one in the project’s Project plans tab.')
        selected = st.session_state.get('planning_alternatives', {}).get(project_id)
        options = [None, *by_id]
        identity = st.selectbox('Alternative scenario', options,
            index=options.index(selected) if selected in options else 0,
            format_func=lambda value: 'Active plan only' if value is None else f'{by_id[value].name} · v{by_id[value].version}',
            key=f'gantt_alternative_{project_id}')
        if st.button('Display scenario', type='primary'):
            choices = dict(st.session_state.get('planning_alternatives', {}))
            if identity is None:
                choices.pop(project_id, None)
            else:
                workspace.plans.comparison(project_id, identity)
                choices[project_id] = identity
                st.session_state['planning_show_baseline'] = False
            st.session_state['planning_alternatives'] = choices
            st.rerun()
    except (ValueError, PlanningStorageError) as error:
        st.error(str(error))


def scenario_payload(workspace: PlanningWorkspace, project_ids: list[int]) -> dict:
    """Read only selected visible alternatives; never feed them to pool demand."""
    alternatives = {}
    contents = []
    choices = st.session_state.setdefault('planning_alternatives', {})
    if workspace.plans is not None:
        permissions = workspace.projects.projects.permissions()
        for project_id, plan_id in list(choices.items()):
            if project_id not in project_ids:
                choices.pop(project_id)
                continue
            try:
                plan, tasks = workspace.plans.comparison(project_id, plan_id)
            except ValueError:
                choices.pop(project_id)
                continue
            alternatives[project_id] = dict(id=plan.id, revision=plan.revision, name=plan.name, tasks=tasks,
                dependencies=plan.content.dependencies, status=plan.status,
                editable=permissions.allows(Permission.EDIT, project_id))
            contents.append(plan.content)
    return dict(edit_enabled=bool(st.session_state.get('planning_edit_enabled', False)), alternatives=alternatives,
                alternative_endpoints=workspace.plans.comparison_endpoints(contents) if contents else {},
                scenario_epoch=st.session_state.get('planning_scenario_epoch', 0))
