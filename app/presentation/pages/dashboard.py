"""Fragment-local portfolio dashboard and shared read-only allocated-budget view."""

from hashlib import sha256
from html import escape
from functools import partial

import pandas as pd
import streamlit as st

from app.application.exceptions import ProjectStorageError
from app.application.ports.dashboard import DashboardCatalog, OverallocatedPool
from app.application.services.dashboard import DashboardService
from app.domain.access.models import AccessDenied
from app.domain.dashboard import DashboardProject
from app.domain.finance import euro_text
from app.presentation.components.action_table import action_table
from app.presentation.components.dialog import dialog
from app.presentation.components.dashboard_table import dashboard_table
from app.presentation.components.organization_filter_panel import organization_filter_panel
from app.presentation.components.dashboard_resource_chart import finance_chart, resource_chart
from app.presentation.navigation import PAGE_PLANNING, PAGE_SETTINGS
from app.presentation.components.authorized_cache import authorized_cache
from app.presentation.i18n import get_current_locale, t


def _label(key: str) -> str:
    return t('dashboard.' + key)


@authorized_cache(show_spinner=False, max_entries=32, ttl=300)
def _catalog(_service: DashboardService, revision: tuple):
    return _service.catalog()


@authorized_cache(show_spinner=False, max_entries=128, ttl=300)
def _report(_service: DashboardService, revision: tuple, ids: tuple[int, ...], status: str = 'Approved'):
    return _service.report(list(ids), status)


@authorized_cache(show_spinner=False, max_entries=64, ttl=300)
def _shortages(_service: DashboardService, revision: tuple, ids: tuple[int, ...],
               statuses: tuple[str, ...] = (), pool_ids: tuple[int, ...] | None = None):
    return _service.resource_breakdown(list(ids), statuses=list(statuses),
                                       pool_ids=list(pool_ids) if pool_ids is not None else None)


def _queue_pool_filter(pool_ids: list[str]) -> None:
    """Apply a chart selection before the top pool widget is rendered again."""
    st.session_state['dashboard_pending_pool_filter'] = pool_ids
    _reset_page()


def _reset_page() -> None:
    st.session_state['dashboard_offset'] = 0
    st.session_state.pop('dashboard_selected_project', None)


def _clear() -> None:
    st.session_state.pop('dashboard_pending_pool_filter', None)
    for key in list(st.session_state):
        if key.startswith('dashboard_filter_'):
            del st.session_state[key]
    st.session_state['dashboard_flex_fields'] = []
    st.session_state['dashboard_match'] = 'Any'
    st.session_state['dashboard_filter_status'] = ['In Progress']
    _reset_page()


def _source(report, status: str = 'Approved') -> bool:
    label = t('finance.' + status, default=status)
    if report.approved is None:
        st.info(t('dashboard.no_status_budget', status=label))
        return False
    st.caption(t('dashboard.status_source', status=label, number=report.approved.number, name=report.approved.name))
    if report.budget.unmatched:
        st.warning(t('dashboard.unmatched_status', status=label, codes=', '.join(report.budget.unmatched)))
    return True


def _budget_table(report, years: range, include_allocation: bool) -> None:
    code, allocation = t('wbs.code'), t('wbs.allocation')
    rows = [{code: share.code,
             **({allocation: f'{share.percentage}%'} if include_allocation else {}),
             **{str(year): euro_text(values[year]) if year in values else None for year in years}}
            for share, values in report.budget.rows]
    if not rows:
        st.info(_label('no_wbs'))
        return
    rows.append({code: _label('total'), **({allocation: ''} if include_allocation else {}),
                 **{str(year): euro_text(report.budget.totals[year]) if year in report.budget.totals else None for year in years}})
    frame = pd.DataFrame(rows).style.set_properties(
        subset=[code, allocation] if include_allocation else [code], **{'color': '#808080'})
    st.dataframe(frame, hide_index=True, height=min(440, 40+35*len(rows)),
                 column_config={code: st.column_config.TextColumn(pinned=True)})


def render_project_budget(project_id: int, service: DashboardService) -> None:
    """Show latest Approved, Proposed and Draft shares without changing Finance history."""
    try:
        revision = service.revision()
        years = range(service.today().year-5, service.today().year+15)
        for status in ('Approved', 'Proposed', 'Draft'):
            st.subheader(t('finance.' + status, default=status))
            report = _report(service, revision, (project_id,), status)
            if _source(report, status):
                _budget_table(report, years, status == 'Draft')
    except (AccessDenied, ProjectStorageError):
        st.error(_label('unavailable'))


@dialog('Issues', width='large')
def _issues(service: DashboardService, ids: tuple[int, ...]) -> None:
    try:
        rows = service.issues(list(ids), get_current_locale())
        st.subheader(_label('issues'))
        for row in rows:
            row['status'] = t('project_collaboration.state_' + row['status'], default=row['status'])
            row['scope'] = t('project_collaboration.scope_' + row['scope'], default=row['scope'])
        action_table(rows, [('project_name', _label('project')), ('title', _label('issue_title')),
                           ('event_type', _label('event_type')), ('status', _label('status')),
                           ('description', _label('description')), ('comment', _label('comment')),
                           ('deadline', _label('deadline')), ('scope', _label('scope'))], {}, key='dashboard_issues')
        if not rows:
            st.info(_label('no_issues'))
    except (AccessDenied, ProjectStorageError):
        st.error(_label('unavailable'))


def _filters(service: DashboardService, catalog) -> tuple[dict[str, list[str]], bool]:
    if 'dashboard_pending_pool_filter' in st.session_state:
        st.session_state['dashboard_filter_pool'] = st.session_state.pop('dashboard_pending_pool_filter')
    fixed = ('status', 'service', 'division', 'org_team', 'org_manager', 'pool')
    st.session_state.setdefault('dashboard_filter_status', ['In Progress'])
    st.session_state['dashboard_filter_status'] = [
        'In Progress' if value == 'Active' else value
        for value in st.session_state['dashboard_filter_status']
    ]
    fields = {'name': _label('project'),
              'project_manager': _label('manager'), 'level_3_manager_name': _label('level3'),
              '_project_tags': t('planning.flex_filter_project_tags', default='Project tags')}
    for parameter in catalog.parameters:
        label = parameter.get('translations', {}).get(get_current_locale()) or parameter.get('alias') or parameter['param_name']
        fields[parameter['param_id']] = label + (f" ({parameter['param_id']})" if label in fields.values() else '')
    selected_fields = [key for key in st.session_state.get('dashboard_flex_fields', []) if key in fields]
    st.session_state['dashboard_flex_fields'] = selected_fields
    organization = organization_filter_panel(
        lambda upstream, key: service.organization_choices(catalog, upstream, key), catalog.labels,
        prefix='dashboard_filter_', on_change=_reset_page,
    )
    active = {key: st.session_state.get('dashboard_filter_' + key, []) for key in (*fixed, *selected_fields)}
    active.update(organization)
    match_all = st.session_state.get('dashboard_match', 'Any') == 'All'

    def choose(key: str, label: str) -> None:
        options = service.choices(catalog, active, key, match_all)
        if key == 'status':
            options = sorted((set(options) - {'Active'}) | {'In Progress'}, key=str.casefold)
        state_key = 'dashboard_filter_' + key
        if state_key in st.session_state:
            st.session_state[state_key] = [value for value in st.session_state[state_key] if value in options]
        labels = catalog.labels.get(key, {})
        active[key] = st.multiselect(label, options, key=state_key, on_change=_reset_page,
                                     format_func=lambda value: labels.get(value, value) or _label('unassigned'))

    columns = st.columns(2, vertical_alignment='top')
    for column, key in zip(columns, ('status', 'pool')):
        with column:
            choose(key, _label('project_status') if key == 'status' else _label(key))
    actions = st.columns(6, vertical_alignment='bottom')
    with actions[-1], st.popover(_label('advanced_filters'), width='stretch', icon=':material/filter_alt:'):
        chosen = st.multiselect(t('planning.flex_filter_fields', default='Filter fields'), list(fields),
                                format_func=fields.get, key='dashboard_flex_fields', on_change=_reset_page)
        match_all = st.segmented_control(t('planning.flex_filter_match_label', default='When several values are selected'),
                                         ['Any', 'All'], default='Any', key='dashboard_match', on_change=_reset_page) == 'All'
        for key in chosen:
            choose(key, fields[key])
        active = {key: values for key, values in active.items() if key in fixed or key in chosen}
    with actions[0]:
        st.button(t('planning.clear_all_filters', default='Clear all filters'), on_click=_clear,
                  icon=':material/filter_alt_off:', key='dashboard_clear')
    return active, match_all


@st.fragment
def _projects(service: DashboardService) -> None:
    """Reauthorize each lazy page without rerunning charts or the application shell."""
    try:
        filters, match_all = st.session_state.get('dashboard_active_filters', ({}, False))
        _project_page(service, filters, match_all)
    except (AccessDenied, ProjectStorageError):
        st.error(_label('unavailable'))


def _project_page(service: DashboardService, filters: dict[str, list[str]], match_all: bool) -> None:
    revision = service.revision()
    projects = _matching_projects(service, _catalog(service, revision), filters, match_all)
    token = sha256(repr((revision, [row['id'] for row in projects])).encode()).hexdigest()
    request = st.session_state.get('dashboard_project_table', {}).get('request', {})
    offset = request.get('offset', 0) if isinstance(request, dict) and request.get('token') == token else 0
    offset = min(max(0, offset), max(0, len(projects)-1)) if type(offset) is int else 0
    offset = offset // 50 * 50
    with st.expander(t('dashboard.matching', count=len(projects)), expanded=False, key='dashboard_project_list'):
        rows = [{'id': row['id'], 'values': [row['name'],
                ', '.join(row['fields'].get('PRM_001', [])), ', '.join(row['fields'].get('PRM_008', [])),
                ', '.join(row['fields'].get('PRM_027', []))]} for row in projects[offset:offset+50]]
        dashboard_table(rows, [_label(key) for key in ('project', 'mail_code', 'phase', 'priority')],
                        len(projects), offset, token, _label('loading'),
                        st.session_state.get('dashboard_selected_project'),
                        partial(_select_project, service, token))


def _matching_projects(service: DashboardService, catalog: DashboardCatalog,
                       filters: dict[str, list[str]], match_all: bool) -> list[DashboardProject]:
    """Apply the row selection on top of the authorized dashboard filters."""
    projects = service.filtered(catalog, filters, match_all)
    selected = st.session_state.get('dashboard_selected_project')
    return [row for row in projects if row['id'] == selected] if selected is not None else projects


def _select_project(service: DashboardService, token: str) -> None:
    """Toggle a currently readable row and refresh only the Dashboard fragment."""
    event = st.session_state.get('dashboard_project_table', {}).get('project')
    if not isinstance(event, dict) or event.get('token') != token or type(event.get('id')) is not int:
        return
    try:
        catalog = _catalog(service, service.revision())
        filters, match_all = st.session_state.get('dashboard_active_filters', ({}, False))
        allowed = {row['id'] for row in _matching_projects(service, catalog, filters, match_all)}
        if event['id'] not in allowed:
            return
        selected = st.session_state.get('dashboard_selected_project')
        st.session_state['dashboard_selected_project'] = None if selected == event['id'] else event['id']
    except (AccessDenied, ProjectStorageError):
        st.session_state['dashboard_selection_error'] = True
    st.rerun('dashboard')


def _finance_chart(service: DashboardService, report, proposed) -> None:
    """Display both authorized budget snapshots on the shared dashboard timeline."""
    years = range(service.today().year - 2, service.today().year + 10)
    series = [
        {'name': t('finance.' + status, default=status),
         'points': [{'date': f'{year}-01-01',
                     'value': float(snapshot.budget.totals[year])
                     if year in snapshot.budget.totals else None} for year in years]}
        for status, snapshot in [('Approved', report), ('Proposed', proposed)]
    ]
    finance_chart(series=series, today=service.today().isoformat(), year=service.today().year,
                  locale=get_current_locale(), title=_label('finance_overview'), value_label=_label('euros'))


def _planning_jump(service: DashboardService, ids: tuple[int, ...], quarter: str,
                   pool_id: int | None = None, metric: str = 'overallocation') -> None:
    projects = service.consuming_projects(list(ids), quarter, pool_id, metric,
                                          statuses=st.session_state.get('dashboard_filter_status'))
    if not projects:
        st.info(_label('no_consumers'))
        return
    st.session_state['dashboard_planning_projects'] = projects
    st.session_state['nav_redirect'] = PAGE_PLANNING
    st.rerun()


def _pool_warning(pools: list[OverallocatedPool]) -> None:
    """Show a matching warning frame with a names-only hover/focus overlay."""
    label = _label('overassigned_pool' if len(pools) <= 1 else 'overassigned_pools')
    color = '#df8b16' if pools else '#23934c'
    names = ''.join(f'<li>{escape(pool["name"])}</li>' for pool in pools)
    overlay = f'<ul role="tooltip" id="dashboard-pool-warning-list">{names}</ul>' if names else ''
    description = 'aria-describedby="dashboard-pool-warning-list"' if pools else ''
    with st.container(border=True, key='dashboard_pool_warning_card'):
        st.html(f'''<style>
        .dashboard-pool-warning {{position:relative;text-align:center;color:{color};outline-offset:4px}}
        .dashboard-pool-warning .warning-icon {{height:90px;display:flex;align-items:center;justify-content:center}}
        .dashboard-pool-warning .warning-symbol {{font-family:"Material Symbols Rounded";
            font-size:52px;line-height:1;font-weight:400;font-style:normal;
            font-feature-settings:"liga";text-transform:none;letter-spacing:normal}}
        .dashboard-pool-warning p {{margin:0; color:{color if pools else '#000000'}}}
        .dashboard-pool-warning ul {{display:none;position:absolute;right:100%;top:0;z-index:1000;
            min-width:220px;max-width:340px;max-height:360px;overflow:auto;margin:0;padding:12px 24px;
            text-align:left;color:var(--st-text-color,#111);background:var(--st-background-color,#fff);
            border:1px solid #848486;border-radius:8px;box-shadow:0 4px 18px #0003}}
        .dashboard-pool-warning:hover ul,.dashboard-pool-warning:focus-within ul {{display:block}}
        </style><div class="dashboard-pool-warning" tabindex="0" {description}>
        <div class="warning-icon" aria-hidden="true"><span class="warning-symbol" translate="no">warning</span></div>
        <p>{len(pools)} {escape(label)}</p>{overlay}</div>''')


def _pool_details_jump(service: DashboardService, ids: tuple[int, ...], quarter: str,
                       pool_id: int, metric: str) -> None:
    """Reauthorize the selected chart pool before opening its existing details."""
    service.consuming_projects(list(ids), quarter, pool_id, metric,
                               statuses=st.session_state.get('dashboard_filter_status'))
    st.session_state['settings_active_section'] = 'organization'
    st.session_state['rb_settings_section'] = 'org_structure'
    st.session_state['settings_active_tab'] = 'resource_pools'
    st.session_state['target_resource_pool_id'] = pool_id
    st.session_state['nav_redirect'] = PAGE_SETTINGS
    st.rerun()


@st.fragment(key='dashboard')
def render_dashboard(service: DashboardService) -> None:
    """Update filters, five-row pages and charts independently of the application shell."""
    st.html("""<style>
    .stMainBlockContainer:has(.st-key-dashboard_filter_pool){padding-top:.25rem!important}
    .st-key-dashboard_issue_count button{background:transparent!important;border:0!important;color:var(--issue-icon)!important;min-height:90px;width:100%;justify-content:center}
    .st-key-dashboard_issue_count button > div{justify-content:center!important;width:100%}
    .st-key-dashboard_issue_count button [data-testid=stMarkdownContainer]{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
    .st-key-dashboard_issue_count button [data-testid=stIconMaterial]{font-size:52px!important;width:52px!important;height:52px!important;flex:0 0 52px;line-height:1;color:var(--issue-icon)!important}
    .st-key-dashboard_issue_count button:disabled{opacity:1!important}
    .st-key-dashboard_issue_card [data-testid=stMarkdownContainer]{text-align:center;color:var(--issue-text)}
    </style>""")
    if st.session_state.pop('dashboard_selection_error', False):
        st.error(_label('unavailable'))
    try:
        revision = service.revision()
        catalog = _catalog(service, revision)
        filters, match_all = _filters(service, catalog)
        projects = _matching_projects(service, catalog, filters, match_all)
        # A queued scroll callback can retain an older fragment invocation.
        # Read the latest filter snapshot inside the fragment, not its old arguments.
        st.session_state['dashboard_active_filters'] = (filters, match_all)
        _projects(service)
        if not projects:
            st.info(_label('no_projects'))
            return
        ids = tuple(row['id'] for row in projects)
        report = _report(service, revision, ids)
        proposed = _report(service, revision, ids, 'Proposed')
        finance, issues = st.columns([8, 1.5], gap=None, vertical_alignment='top')
        with finance:
            st.subheader(_label('finance_overview'))
            approved_source, proposed_source = st.columns(2)
            with approved_source:
                _source(report)
            with proposed_source:
                _source(proposed, 'Proposed')
        with issues, st.container(border=True, key='dashboard_issue_card'):
            icon_color = '#df8b16' if report.issue_count else '#23934c'
            text_color = '#df8b16' if report.issue_count else '#000000'
            st.html(f'<style>.st-key-dashboard_issue_card{{--issue-icon:{icon_color};--issue-text:{text_color}}}</style>')
            issue_label = _label('active_issue' if report.issue_count <= 1 else 'active_issues')
            if st.button(issue_label, icon=':material/warning:', key='dashboard_issue_count', width='stretch',
                         disabled=report.issue_count == 0,
                         help=t('dashboard.issue_count', count=report.issue_count)) and report.issue_count:
                _issues(service, ids)
            st.markdown(f"{report.issue_count} {issue_label}")
        with finance:
            _finance_chart(service, report, proposed)
            selected_pools = filters.get('pool', [])
            chart_pools = tuple(int(value) for value in selected_pools if value.isdigit()) if selected_pools else None
            series = _shortages(service, revision, ids, tuple(filters.get('status', [])), chart_pools)
            st.subheader(_label('resources_allocation'))
            st.caption(_label('individual_pool_peaks'))
            pool_names = {pool['pool_id']: pool['name'] for pool in series['pools']}
            if selected_pools:
                st.caption(t('dashboard.filtered_pool', pool=', '.join(pool_names.values())))
                st.button(_label('clear_pool_filter'), key='dashboard_clear_chart_pool',
                          on_click=_queue_pool_filter, args=([],))
            st.html('<style>.st-key-dashboard_resource_charts {gap:4px !important;}</style>')
            with st.container(key='dashboard_resource_charts'):
                for metric in ('overallocation', 'allocation'):
                    selection = resource_chart(series, today=service.today().isoformat(),
                        year=service.today().year, locale=get_current_locale(), metric=metric, labels={
                            'title': _label(metric), 'valueLabel': _label(metric), 'totalValueLabel': _label('total_' + metric),
                            'totalCapacityLabel': _label('total_capacity_short'),
                            'totalLabel': _label('total'), 'allocatedLabel': _label('allocation'),
                            'availableLabel': t('planning.resource_grid.available_value', default='Available'),
                            'capacityLabel': _label('total_capacity'), 'goTo': _label('go_to_consumers'),
                            'poolDetails': _label('pool_details'), 'filterPool': _label('filter_pool'),
                            'portfolioPeakLabel': _label('simultaneous_peak')})
                    if isinstance(selection, dict) and selection.get('metric') == metric:
                        if type(selection.get('pool_id')) is not int or not isinstance(selection.get('quarter'), str):
                            raise ValueError('Invalid resource selection.')
                        action = selection.get('action', 'planning')
                        if action == 'pool_details':
                            _pool_details_jump(service, ids, selection['quarter'], selection['pool_id'], metric)
                        elif action == 'planning':
                            _planning_jump(service, ids, selection['quarter'], selection['pool_id'], metric)
                        elif action == 'filter_pool' and selection['pool_id'] in pool_names:
                            _queue_pool_filter([str(selection['pool_id'])])
                            st.rerun(scope='fragment')
                        else:
                            raise ValueError('Invalid resource action.')
        with issues:
            _pool_warning(series.get('overallocated_pools', []))
    except (AccessDenied, ProjectStorageError, ValueError):
        st.error(_label('unavailable'))
