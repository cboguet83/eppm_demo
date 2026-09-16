"""Project plan selection, immutable draft editing and paired Gantt comparison."""

from copy import deepcopy
from dataclasses import asdict
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from app.domain.access.models import Permission
from app.domain.planning.plans import PlanContent, ProjectPlan, normalize_content
from app.domain.planning.schedule_template import parse_template
from app.domain.planning.plan_comparison import dependency_warnings
from app.domain.resources.models import PoolAssignment
from app.presentation.components.plan_gantt import comparison_project, plan_gantt
from app.presentation.components.planning_workspace import PlanningWorkspace


def _label(plan: ProjectPlan) -> str:
    marks = [name for name, enabled in [('Current', plan.is_current), ('Baseline', plan.is_baseline)] if enabled]
    return f'{plan.name} · v{plan.version} · {plan.status.title()}' + (' · ' + ', '.join(marks) if marks else '')


def _discard(project_id: int) -> None:
    st.session_state['plan_drafts'].pop(project_id, None)


def _new_draft(plan: ProjectPlan, content: PlanContent | None = None) -> dict:
    source = content if content is not None else plan.content
    return dict(source=plan.id, revision=plan.revision, base=deepcopy(source),
                content=deepcopy(source), epoch=0, name=f'{plan.name} alternative', status='proposed')


def _task_editor(project_id: int, draft: dict) -> list[dict]:
    base = draft['base']
    columns = ['id', 'task_name', 'phase', 'start_date', 'end_date', 'description']
    frame = pd.DataFrame(base.tasks, columns=columns)
    for column in ['start_date', 'end_date']:
        frame[column] = pd.to_datetime(frame[column]).dt.date
    edited = st.data_editor(frame, hide_index=True, num_rows='dynamic', width='stretch',
        disabled=['id'], key=f'plan_tasks_{project_id}_{draft["epoch"]}', column_config={
            'id': None, 'task_name': st.column_config.TextColumn('Task name', required=True),
            'phase': 'Phase', 'description': 'Description',
            'start_date': st.column_config.DateColumn('Start date', required=True),
            'end_date': st.column_config.DateColumn('End date', required=True),
        })
    rows = []
    negative = min([0, *(row['id'] for row in base.tasks)]) - 1
    for row in edited.to_dict('records'):
        if pd.isna(row['id']):
            row['id'], negative = negative, negative - 1
        row['id'] = int(row['id'])
        for column in ['start_date', 'end_date']:
            row[column] = str(row[column]) if pd.notna(row[column]) else ''
        for column in ['task_name', 'phase', 'description']:
            row[column] = str(row[column]) if pd.notna(row[column]) else ''
        rows.append(row)
    return rows


def _task_labels(tasks: list[dict]) -> dict[int, str]:
    """Disambiguate duplicate names without requiring users to enter identities."""
    names = [row['task_name'] for row in tasks]
    return {row['id']: row['task_name'] if names.count(row['task_name']) == 1
            else f'{row["task_name"]} ({index + 1})' for index, row in enumerate(tasks)}


def _dependency_editor(project_id: int, draft: dict, tasks: list[dict],
                       projects: dict[int, str], external: dict[int, str]) -> list[dict]:
    labels = _task_labels(tasks)
    predecessors = external | labels
    for dep in draft['base'].dependencies:
        identity = dep['predecessor_task_id']
        if identity is not None and identity not in predecessors:
            predecessors[identity] = f'Task absent from current schedule ({identity})'
    st.caption('An empty successor means the whole project. Select either a predecessor task or project.')
    columns = ['task_id', 'predecessor_task_id', 'predecessor_project_id', 'link_type', 'lag_days']
    frame = pd.DataFrame([row for row in draft['base'].dependencies
                          if row['task_id'] is None or row['task_id'] in labels], columns=columns)
    choices = [labels, predecessors, {key: value for key, value in projects.items() if key != project_id}]
    for column, options in zip(columns[:3], choices):
        frame[column] = frame[column].map(options)
    edited = st.data_editor(frame, hide_index=True, num_rows='dynamic', width='stretch',
        key=f'plan_dependencies_{project_id}_{draft["epoch"]}', column_config={
            'task_id': st.column_config.SelectboxColumn('Successor task', options=list(labels.values())),
            'predecessor_task_id': st.column_config.SelectboxColumn('Predecessor task', options=list(predecessors.values())),
            'predecessor_project_id': st.column_config.SelectboxColumn('Predecessor project', options=list(choices[2].values())),
            'link_type': st.column_config.SelectboxColumn('Type', options=['FS', 'FF', 'SS', 'SF'], default='FS'),
            'lag_days': st.column_config.NumberColumn('Lag (days)', default=0, step=1),
        })
    result = []
    for row in edited.to_dict('records'):
        if pd.notna(row['task_id']) and row['task_id'] not in labels.values():
            continue
        for key, options in zip(columns[:3], choices):
            row[key] = {value: identity for identity, value in options.items()}.get(row[key])
        row['lag_days'] = int(row['lag_days']) if pd.notna(row['lag_days']) else 0
        row['link_type'] = row['link_type'] if pd.notna(row['link_type']) else 'FS'
        # Removing a successor also removes its incoming dependencies.
        if row['task_id'] is None or row['task_id'] in labels:
            result.append(row)
    return result


def _assignment_editor(project_id: int, draft: dict, tasks: list[dict], pools: dict[int, str]) -> list[PoolAssignment]:
    st.caption('Leave Task empty for project-level demand. Relative dates follow the selected task/project schedule.')
    labels = _task_labels(tasks)
    columns = ['id', 'pool_id', 'task_id', 'fte_assigned', 'start_date', 'end_date',
               'schedule_anchor', 'offset_days', 'duration_days', 'notes']
    frame = pd.DataFrame([asdict(row) for row in draft['base'].assignments
                          if row.task_id is None or row.task_id in labels], columns=columns)
    frame['pool_id'] = frame['pool_id'].map(lambda identity: pools.get(identity, f'Unavailable pool #{identity}'))
    frame['task_id'] = frame['task_id'].map(labels)
    edited = st.data_editor(frame, hide_index=True, num_rows='dynamic', width='stretch', disabled=['id'],
        key=f'plan_assignments_{project_id}_{draft["epoch"]}', column_config={
            'id': None, 'pool_id': st.column_config.SelectboxColumn('Pool', options=list(pools.values()), required=True),
            'task_id': st.column_config.SelectboxColumn('Task', options=list(labels.values())),
            'fte_assigned': st.column_config.NumberColumn('FTE', min_value=0, default=1.0),
            'start_date': 'Start date (YYYY-MM-DD)', 'end_date': 'Stop date (YYYY-MM-DD)',
            'schedule_anchor': st.column_config.SelectboxColumn('Relative anchor', options=['start', 'end']),
            'offset_days': st.column_config.NumberColumn('Offset days', step=1),
            'duration_days': st.column_config.NumberColumn('Duration days', min_value=1, step=1),
            'notes': 'Notes',
        })
    ids = {label: identity for identity, label in pools.items()}
    task_ids = {row['id'] for row in tasks}
    result = []
    for row in edited.to_dict('records'):
        row = {key: value if pd.notna(value) else None for key, value in row.items()}
        if row['task_id'] is not None and row['task_id'] not in labels.values():
            continue
        row['task_id'] = {name: identity for identity, name in labels.items()}.get(row['task_id'])
        for key in ['id', 'offset_days', 'duration_days']:
            if row[key] is not None:
                row[key] = int(row[key])
        if row['task_id'] is not None and row['task_id'] not in task_ids:
            continue
        if row['pool_id'] not in ids:
            raise ValueError('Select an assignable pool for each resource assignment.')
        row['pool_id'] = ids[row['pool_id']]
        row['notes'] = row['notes'] or ''
        row['fte_assigned'] = float(row['fte_assigned'] or 0)
        result.append(PoolAssignment(project_id=project_id, **row))
    return result


def _render_draft(project_id: int, draft: dict, pools: dict[int, str], tag_choices: dict[int, str],
                  projects: dict[int, str], external: dict[int, str]) -> None:
    with st.expander('Edit alternative · unsaved draft', expanded=True):
        draft['name'] = st.text_input('New plan name', value=draft['name'], key=f'plan_name_{project_id}_{draft["epoch"]}')
        draft['status'] = st.selectbox('New plan status', ['proposed', 'draft'],
            format_func=str.title, key=f'plan_new_status_{project_id}_{draft["epoch"]}')
        tasks_tab, dependencies_tab, resources_tab, tags_tab = st.tabs(['Tasks', 'Dependencies', 'Resource assignments', 'Task tags'])
        with tasks_tab:
            tasks = _task_editor(project_id, draft)
            with st.expander('Import task CSV template'):
                uploaded = st.file_uploader('CSV template', type=['csv'], key=f'plan_csv_{project_id}_{draft["epoch"]}')
                st.caption('Import replaces tasks in this draft. The saved source plan is preserved.')
                if st.button('Import into draft', key=f'plan_import_{project_id}', disabled=uploaded is None):
                    steps = parse_template(uploaded.getvalue().decode('utf-8-sig'))
                    imported = PlanContent()
                    for step in steps:
                        imported.tasks.append(dict(id=-step.number, **{key: step.values.get(key, '') for key in
                            ['task_name', 'phase', 'start_date', 'end_date', 'description']}))
                        for dep in step.dependencies:
                            imported.dependencies.append(dict(task_id=-step.number,
                                predecessor_task_id=-dep.identity if dep.kind == 'step' else dep.identity if dep.kind == 'task' else None,
                                predecessor_project_id=dep.identity if dep.kind == 'project' else None,
                                link_type=dep.link_type, lag_days=dep.lag_days))
                    draft['base'] = draft['content'] = normalize_content(project_id, imported)
                    draft['epoch'] += 1
                    st.rerun()
        with dependencies_tab:
            dependencies = _dependency_editor(project_id, draft, tasks, projects, external)
        with resources_tab:
            assignments = _assignment_editor(project_id, draft, tasks, pools)
        task_tags = {}
        with tags_tab:
            labels = _task_labels(tasks)
            tags = tag_choices
            frame = pd.DataFrame([{'task': labels[identity], 'tag': tags.get(tag['tag_id']), 'free_text': tag['free_tag']}
                for identity, values in draft['base'].task_tags.items() if identity in labels for tag in values],
                columns=['task', 'tag', 'free_text'])
            edited = st.data_editor(frame, hide_index=True, num_rows='dynamic', width='stretch',
                key=f'plan_tags_{project_id}_{draft["epoch"]}', column_config={
                    'task': st.column_config.SelectboxColumn('Task', options=list(labels.values()), required=True),
                    'tag': st.column_config.SelectboxColumn('Tag', options=list(tags.values())),
                    'free_text': st.column_config.TextColumn('Free text'),
                })
            task_by_label, tag_by_label = {v: k for k, v in labels.items()}, {v: k for k, v in tags.items()}
            for row in edited.to_dict('records'):
                if row['task'] in task_by_label:
                    task_tags.setdefault(task_by_label[row['task']], []).append(dict(
                        tag_id=tag_by_label.get(row['tag']), free_tag=row['free_text'] if pd.notna(row['free_text']) else None))
        draft['content'] = PlanContent(tasks, dependencies, assignments,
                                      task_tags)
        st.button('Cancel draft', key=f'plan_cancel_{project_id}', on_click=_discard, args=(project_id,))


def _actual_progress(workspace: PlanningWorkspace, current: ProjectPlan, editable: bool) -> None:
    """Edit live progress independently of immutable schedule versions."""
    with st.expander('Actual progress · current plan'):
        rows = workspace.planning.get_milestones_by_project(current.project_id)
        frame = pd.DataFrame([{'id': row['id'], 'Task': row['task_name'],
                               'Progress (%)': row['progress_pct'] or 0} for row in rows],
                             columns=['id', 'Task', 'Progress (%)'])
        edited = st.data_editor(frame, hide_index=True, disabled=['id', 'Task'] if editable else True,
            width='stretch', key=f'plan_actuals_{current.project_id}_{current.id}',
            column_config={'id': None, 'Progress (%)': st.column_config.NumberColumn(min_value=0, max_value=100, step=1, required=True)})
        if st.button('Save progress', key=f'plan_save_actuals_{current.project_id}', disabled=not editable):
            previous = {row['id']: row['progress_pct'] or 0 for row in rows}
            for row in edited.to_dict('records'):
                if row['Progress (%)'] != previous[row['id']]:
                    workspace.planning.update_progress(int(row['id']), int(row['Progress (%)']))
            st.toast('Actual progress saved.')
            st.rerun()


def render_project_plans(workspace: PlanningWorkspace) -> None:
    """Select reference/alternative plans per project and save drafts atomically."""
    service = workspace.plans
    if service is None:
        return
    permissions = workspace.projects.projects.permissions()
    catalog = workspace.projects.projects.get_planning_catalog()
    names = {row['id']: row['name'] for row in catalog}
    drafts = st.session_state.setdefault('plan_drafts', {})
    for project_id, identity in st.session_state.pop('plan_pending_selection', {}).items():
        st.session_state[f'plan_alternative_{project_id}'] = identity
    st.markdown('### Project plans')
    st.caption('Compare reference and alternative schedules. Save creates a new scenario. Use Set current to activate it.')
    initial = st.session_state.get('target_planning_project_id')
    default = [initial] if initial in names else list(names)[:1]
    selected = st.multiselect('Projects to compare', list(names), default=default,
        format_func=names.get, key='plan_projects', disabled=bool(drafts))
    pool_rows = workspace.resources.get_all_pools()
    parent_ids = {row.parent_pool_id for row in pool_rows}
    pools = {row.id: f'{row.name} [#{row.id}]' for row in pool_rows if row.id not in parent_ids}
    transport = []
    reference_plans, alternative_plans = {}, {}
    task_choices = service.task_choices() if drafts else []
    for project_id in selected:
        plans = service.list_plans(project_id)
        editable = permissions.allows(Permission.EDIT, project_id)
        admin = permissions.allows(Permission.SHARED)
        approver = admin or permissions.allows(Permission.APPROVE, project_id)
        if not plans:
            if editable:
                service.initialize(project_id)
                st.rerun()
            st.info(f'{names[project_id]} has no saved plan yet. A project editor can initialize it.')
            continue
        st.markdown(f'#### {names[project_id]}')
        live = [plan for plan in plans if plan.status != 'deleted']
        by_id = {plan.id: plan for plan in live}
        if not live:
            st.info('This project has no active or alternative plan. Restore a deleted plan to continue.')
            if admin:
                for plan in plans:
                    if st.button('Restore ' + _label(plan), key=f'plan_restore_{plan.id}'):
                        service.change(project_id, plan.id, plan.revision, 'status', 'proposed')
                        st.rerun()
            continue
        current = next((plan for plan in live if plan.is_current), live[0])
        if not current.is_current:
            st.info('No active plan. Select an approved scenario and choose Set current to activate it.')
        baseline = next((plan for plan in live if plan.is_baseline), current)
        for key, fallback in [(f'plan_reference_{project_id}', baseline.id), (f'plan_alternative_{project_id}', current.id)]:
            if key in st.session_state and st.session_state[key] not in by_id:
                st.session_state[key] = fallback
        reference_col, alternative_col = st.columns(2)
        reference_id = reference_col.selectbox('Reference plan', list(by_id), index=list(by_id).index(baseline.id),
            format_func=lambda identity: _label(by_id[identity]), key=f'plan_reference_{project_id}', disabled=project_id in drafts)
        alternative_id = alternative_col.selectbox('Alternative plan', list(by_id), index=list(by_id).index(current.id),
            format_func=lambda identity: _label(by_id[identity]), key=f'plan_alternative_{project_id}', disabled=project_id in drafts)
        alternative, reference = by_id[alternative_id], by_id[reference_id]
        alternative_content = service.current_content(project_id) if alternative.is_current else alternative.content
        with st.container(horizontal=True):
            if st.button('Edit alternative', key=f'plan_edit_{project_id}', disabled=not editable or project_id in drafts):
                drafts[project_id] = _new_draft(alternative, alternative_content)
                st.rerun()
            status = st.selectbox('Plan status', ['draft', 'proposed', 'approved', 'rejected', 'deleted'],
                index=['draft', 'proposed', 'approved', 'rejected', 'deleted'].index(alternative.status),
                format_func=str.title, key=f'plan_status_{project_id}_{alternative.id}_{alternative.revision}',
                disabled=project_id in drafts or not (editable or approver))
            if st.button('Apply status', key=f'plan_apply_status_{project_id}', disabled=project_id in drafts or not (editable or approver)):
                service.change(project_id, alternative.id, alternative.revision, 'status', status)
                if status == 'deleted':
                    st.session_state['plan_pending_selection'] = {project_id: current.id}
                st.rerun()
            approved = alternative.status == 'approved' and approver and project_id not in drafts
            if st.button('Set current', key=f'plan_current_{project_id}', disabled=not approved or alternative.is_current):
                service.change(project_id, alternative.id, alternative.revision, 'current', 'true')
                st.rerun()
            if st.button('Clear baseline' if alternative.is_baseline else 'Set baseline', key=f'plan_baseline_{project_id}', disabled=not approved):
                service.change(project_id, alternative.id, alternative.revision, 'baseline', str(not alternative.is_baseline).lower())
                st.rerun()
        if admin:
            archived = [plan for plan in plans if plan.status == 'deleted']
            if archived:
                with st.expander('Deleted plans'):
                    for plan in archived:
                        st.text(_label(plan))
                        if st.button('Restore as Proposed', key=f'plan_restore_{plan.id}'):
                            service.change(project_id, plan.id, plan.revision, 'status', 'proposed')
                            st.rerun()
        if project_id in drafts:
            external = {row['id']: f'{names.get(row["project_id"], "Project")} / {row["task_name"]} (#{row["id"]})'
                        for row in task_choices if row['project_id'] != project_id}
            _render_draft(project_id, drafts[project_id], pools, service.tag_choices(), names, external)
        if current.is_current:
            _actual_progress(workspace, current, editable)
        content = drafts[project_id]['content'] if project_id in drafts else alternative_content
        if project_id in drafts:
            try:
                content = normalize_content(project_id, content)
            except ValueError as error:
                st.info(f'Complete the draft to preview it: {error}')
                content = alternative_content
        reference_plans[project_id], alternative_plans[project_id] = reference.content, content
        transport.append(comparison_project(project_id, names[project_id], reference.content, content,
            _label(reference), _label(alternative), editable=project_id in drafts))
    event = plan_gantt(transport)
    if event and event.get('nonce') != st.session_state.get('plan_drag_nonce'):
        st.session_state['plan_drag_nonce'] = event.get('nonce')
        draft = drafts[event['project_id']]
        content = deepcopy(draft['content'])
        for task in content.tasks:
            if task['id'] == event['id']:
                for key in ['start_date', 'end_date']:
                    task[key] = (date.fromisoformat(task[key]) + timedelta(days=event['days'])).isoformat()
        draft['base'] = draft['content'] = normalize_content(event['project_id'], content)
        draft['epoch'] += 1
        st.rerun()
    if transport:
        # Add non-selected current schedules solely for cross-project endpoints.
        context = service.dependency_context([*reference_plans.values(), *alternative_plans.values()])
        for label, selection in [('Reference', reference_plans), ('Alternative', alternative_plans)]:
            warnings = dependency_warnings(context | selection)
            for project_id in selected:
                for warning in warnings.get(project_id, []):
                    st.warning(f'{label} · {names[project_id]} · {warning}')
        if st.checkbox('Show resource impact', key='plan_resource_impact'):
            pool_ids = list(pools)
            before, after = workspace.capacity.compare_plan_capacity(pool_ids, reference_plans, alternative_plans, names)
            st.caption('Both sides use the same live capacity. Other projects retain their current-plan demand.')
            for column, label, values in zip(st.columns(2), ['Reference', 'Alternative'], [before, after]):
                with column:
                    st.markdown(f'**{label} resource demand**')
                    st.dataframe(pd.DataFrame([{'Pool': row.pool_name, 'Peak FTE': row.peak_assigned_fte,
                        'Peak excess FTE': row.peak_excess_fte} for row in values]), hide_index=True, width='stretch')
    if drafts:
        st.warning('Unsaved alternative plans. Save as new plans or cancel drafts before changing projects.')
        if st.button('Save as new plan' if len(drafts) == 1 else 'Save all as new plans', type='primary', key='save_project_plans'):
            saved = service.save_many([(project_id, item['source'], item['revision'], item['name'], item['content'], item['status'])
                                       for project_id, item in drafts.items()])
            st.session_state['plan_pending_selection'] = {plan.project_id: plan.id for plan in saved}
            drafts.clear()
            st.toast('New plans saved. Current plans and baselines are unchanged.')
            st.rerun()
