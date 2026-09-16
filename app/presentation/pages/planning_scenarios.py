"""Session-owned Gantt edit mode and explicit alternative scenario selection."""

from typing import Any

import streamlit as st

from app.application.exceptions import PlanningStorageError
from app.domain.access.models import Permission
from app.domain.planning.project_dependencies import evaluate_project_dependencies
from app.domain.planning.constraints import evaluate_constraints
from app.presentation.components.dialog import dialog
from app.presentation.components.planning_workspace import PlanningWorkspace


SCENARIO_ACTIONS = frozenset({'toggle_edit', 'toggle_baseline', 'baseline_current_project',
                              'delete_project_baseline', 'choose_alternative', 'update_alternative_dates',
                              'hide_alternatives', 'activate_alternative', 'alternative_action', 'create_alternative'})
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


def close_alternative_view() -> None:
    """Close all comparison lanes without changing plans or portfolio filters."""
    st.session_state['planning_alternatives'] = {}
    st.session_state['planning_new_scenario_views'] = {}
    st.session_state.pop('planning_alternative_editor', None)
    st.session_state.pop('planning_scenario_dialog_project', None)
    st.session_state.pop('planning_create_scenario_project', None)


def handle_scenario_event(event: dict[str, Any], workspace: PlanningWorkspace) -> None:
    """Route validated component JSON; authorization remains in Python services."""
    action = event['action']
    if action == 'alternative_action':
        from app.presentation.pages.planning_alternative_editor import handle_alternative_action

        if event.get('operation') == 'manage_dependencies':
            response = dict(project_id=event['project_id'], nonce=event.get('nonce'), action='save_project_dependencies')
            try:
                handle_alternative_action(event, workspace)
            except (ValueError, PlanningStorageError) as error:
                response['error'] = str(error)
            st.session_state['planning_project_dependency_response'] = response
        else:
            handle_alternative_action(event, workspace)
        return
    if action == 'hide_alternatives':
        close_alternative_view()
        return
    if action == 'toggle_edit':
        st.session_state['planning_edit_enabled'] = event['enabled']
        return
    if action == 'toggle_baseline':
        st.session_state['planning_show_baseline'] = event['enabled']
        if event['enabled']:
            close_alternative_view()
        return
    if action == 'choose_alternative':
        st.session_state['planning_scenario_dialog_project'] = event['project_id']
        return
    if action == 'create_alternative':
        require_edit(alternative=True)
        st.session_state.pop(f'new_scenario_name_{event["project_id"]}', None)
        st.session_state['planning_create_scenario_project'] = event['project_id']
        return
    if workspace.plans is None:
        return
    require_edit(alternative=action in {'update_alternative_dates', 'activate_alternative'})
    if action == 'activate_alternative':
        selected = st.session_state.get('planning_alternatives', {})
        if selected.get(event['project_id']) != event['plan_id']:
            raise ValueError('Select this alternative scenario before activating it.')
        workspace.plans.activate_alternative(event['project_id'], event['plan_id'], event['revision'])
        close_alternative_view()
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


@dialog('Create alternative scenario')
def create_alternative(project_id: int, workspace: PlanningWorkspace) -> None:
    """Name a draft copy of the active plan and immediately open comparison."""
    if workspace.plans is None:
        return
    try:
        require_edit(alternative=True)
        current = next((plan for plan in workspace.plans.list_plans(project_id) if plan.is_current), None)
        if current is None:
            st.error('Activate a project plan before creating an alternative scenario.')
            return
        with st.form(f'create_alternative_{project_id}'):
            name = st.text_input('Scenario name', key=f'new_scenario_name_{project_id}')
            submitted = st.form_submit_button('Create scenario', type='primary')
        if submitted:
            saved = workspace.plans.save(project_id, current.id, current.revision, name)
            st.session_state['planning_alternatives'] = {
                **st.session_state.get('planning_alternatives', {}), project_id: saved.id}
            st.session_state['planning_new_scenario_views'] = {
                **st.session_state.get('planning_new_scenario_views', {}), project_id: saved.id}
            st.session_state['planning_show_baseline'] = False
            st.toast('Draft scenario created.')
            st.rerun()
    except (ValueError, PlanningStorageError) as error:
        st.error(str(error))


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
            st.session_state.get('planning_new_scenario_views', {}).pop(project_id, None)
            st.rerun()
    except (ValueError, PlanningStorageError) as error:
        st.error(str(error))


def scenario_payload(workspace: PlanningWorkspace, project_ids: list[int]) -> dict:
    """Read only selected visible alternatives; never feed them to pool demand."""
    alternatives = {}
    contents = []
    choices = st.session_state.setdefault('planning_alternatives', {})
    new_views = st.session_state.setdefault('planning_new_scenario_views', {})
    if workspace.plans is not None:
        permissions = workspace.projects.projects.permissions()
        for project_id, plan_id in list(choices.items()):
            if project_id not in project_ids:
                choices.pop(project_id)
                new_views.pop(project_id, None)
                continue
            try:
                plan, tasks = workspace.plans.comparison(project_id, plan_id)
            except ValueError:
                choices.pop(project_id)
                new_views.pop(project_id, None)
                continue
            alternatives[project_id] = dict(id=plan.id, revision=plan.revision, name=plan.name, tasks=tasks,
                dependencies=plan.content.dependencies, status=plan.status,
                task_tags=plan.content.task_tags, assignments=plan.content.assignments,
                new_scenario=new_views.get(project_id) == plan.id,
                editable=permissions.allows(Permission.EDIT, project_id))
            contents.append(plan.content)
    if alternatives:
        _enrich_comparisons(workspace, alternatives, contents)
    return dict(edit_enabled=bool(st.session_state.get('planning_edit_enabled', False)), alternatives=alternatives,
                alternative_endpoints=workspace.plans.comparison_endpoints(contents) if contents else {},
                alternative_task_choices=workspace.plans.task_choices() if contents else [],
                scenario_epoch=st.session_state.get('planning_scenario_epoch', 0))


def _enrich_comparisons(workspace: PlanningWorkspace, alternatives: dict, contents: list) -> None:
    """Supply the shared tooltip and dependency panels with scenario-owned values."""
    context = workspace.plans.dependency_context(contents)
    schedules = {identity: content.tasks for identity, content in context.items()}
    schedules.update({identity: [dict(task, id=task['stable_id']) for task in plan['tasks']]
                      for identity, plan in alternatives.items()})
    tasks = {task['id']: dict(task, project_id=identity) for identity, rows in schedules.items() for task in rows}
    bounds = {identity: (min((task['start_date'] for task in rows), default=None),
                         max((task['end_date'] for task in rows), default=None)) for identity, rows in schedules.items()}
    names = {row['id']: row['name'] for row in workspace.projects.projects.get_planning_catalog()}
    tags = {row.id: row for row in workspace.tags.task_tag_choices()}
    pools = {row.id: row.name for row in workspace.resources.get_all_pools()}
    for identity, plan in alternatives.items():
        dependencies = []
        for index, dep in enumerate(plan['dependencies']):
            successor = tasks.get(dep['task_id'])
            predecessor = tasks.get(dep['predecessor_task_id'])
            pred_project = predecessor['project_id'] if predecessor else dep['predecessor_project_id']
            first, last = (successor['start_date'], successor['end_date']) if successor else bounds[identity]
            pred_first, pred_last = ((predecessor['start_date'], predecessor['end_date']) if predecessor
                                      else bounds.get(pred_project, (None, None)))
            dependencies.append(dict(dep, id=index + 1, start_date=first, end_date=last,
                predecessor_owner_id=pred_project, pred_start_date=pred_first, pred_end_date=pred_last,
                predecessor_task_name=predecessor['task_name'] if predecessor else None,
                predecessor_project_name=names.get(pred_project, str(pred_project or 'Unavailable'))))
        task_links, _ = evaluate_constraints(list(tasks.values()), dependencies, bounds)
        project_links = evaluate_project_dependencies([dep for dep in dependencies if dep['task_id'] is None])
        evaluated = {dep['id']: dep for dep in task_links + project_links}
        plan['dependencies'] = [dict(evaluated.get(dep['id'], dep),
            is_evaluable=bool(dep['start_date'] and dep['end_date'] and dep['pred_start_date'] and dep['pred_end_date']))
            for dep in dependencies]
        tag_rows = plan.pop('task_tags')
        pool_rows = {}
        for row in plan.pop('assignments'):
            pool_rows.setdefault(row.task_id, []).append(
                dict(pool_name=pools.get(row.pool_id, str(row.pool_id)), fte=row.fte_assigned))
        violations = {}
        for dep in plan['dependencies']:
            if dep.get('is_violated'):
                violations.setdefault(dep['task_id'], []).append(dep['violation_text'])
        plan['pools'] = pool_rows.get(None, [])
        plan['start'], plan['end'] = bounds[identity]
        for task in plan['tasks']:
            task['project_name'] = names.get(identity, str(identity))
            task['tags'] = [dict(row, tag_name=tags[row['tag_id']].tag if row['tag_id'] in tags else None,
                                tag_group_name=tags[row['tag_id']].tag_group_name if row['tag_id'] in tags else None)
                            for row in tag_rows.get(task['stable_id'], [])]
            task['pools'] = pool_rows.get(task['stable_id'], [])
            task['violations'] = violations.get(task['stable_id'], [])
