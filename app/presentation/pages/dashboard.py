"""Fragment-local portfolio dashboard and shared read-only allocated-budget view."""

from hashlib import sha256
from functools import partial

import pandas as pd
import streamlit as st

from app.application.exceptions import ProjectStorageError
from app.application.ports.dashboard import DashboardCatalog
from app.application.services.dashboard import DashboardService
from app.domain.access.models import AccessDenied
from app.domain.dashboard import DashboardProject
from app.domain.finance import euro_text
from app.presentation.components.action_table import action_table
from app.presentation.components.dialog import dialog
from app.presentation.components.dashboard_table import dashboard_table
from app.presentation.components.dashboard_resource_chart import resource_chart
from app.presentation.navigation import PAGE_PLANNING
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
def _shortages(_service: DashboardService, revision: tuple, ids: tuple[int, ...]):
    return _service.resources(list(ids))


def _reset_page() -> None:
    st.session_state['dashboard_offset'] = 0
    st.session_state.pop('dashboard_selected_project', None)


def _clear() -> None:
    for key in list(st.session_state):
        if key.startswith('dashboard_filter_'):
            del st.session_state[key]
    st.session_state['dashboard_flex_fields'] = []
    st.session_state['dashboard_match'] = 'Any'
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
    fixed = ('level3', 'level4', 'team', 'manager', 'pool')
    fields = {'name': _label('project'), 'status': t('portfolio.col_status', default='Status'),
              'project_manager': _label('manager'), 'level_3_manager_name': _label('level3'),
              '_project_tags': t('planning.flex_filter_project_tags', default='Project tags')}
    for parameter in catalog.parameters:
        label = parameter.get('translations', {}).get(get_current_locale()) or parameter.get('alias') or parameter['param_name']
        fields[parameter['param_id']] = label + (f" ({parameter['param_id']})" if label in fields.values() else '')
    selected_fields = [key for key in st.session_state.get('dashboard_flex_fields', []) if key in fields]
    active = {key: st.session_state.get('dashboard_filter_' + key, []) for key in (*fixed, *selected_fields)}
    match_all = st.session_state.get('dashboard_match', 'Any') == 'All'

    def choose(key: str, label: str) -> None:
        options = service.choices(catalog, active, key, match_all)
        state_key = 'dashboard_filter_' + key
        if state_key in st.session_state:
            st.session_state[state_key] = [value for value in st.session_state[state_key] if value in options]
        labels = catalog.labels.get(key, {})
        active[key] = st.multiselect(label, options, key=state_key, on_change=_reset_page,
                                     format_func=lambda value: labels.get(value, value) or _label('unassigned'))

    columns = st.columns(6, vertical_alignment='bottom')
    with columns[0], st.popover(t('planning.flex_filters', default='Flexible filters'), width='stretch', icon=':material/filter_alt:'):
        chosen = st.multiselect(t('planning.flex_filter_fields', default='Filter fields'), list(fields),
                                format_func=fields.get, key='dashboard_flex_fields', on_change=_reset_page)
        match_all = st.segmented_control(t('planning.flex_filter_match_label', default='When several values are selected'),
                                         ['Any', 'All'], default='Any', key='dashboard_match', on_change=_reset_page) == 'All'
        for key in chosen:
            choose(key, fields[key])
        active = {key: values for key, values in active.items() if key in fixed or key in chosen}
    for column, key in zip(columns[1:], fixed):
        with column:
            choose(key, _label(key))
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
    with st.expander(t('dashboard.matching', count=len(projects)), expanded=True, key='dashboard_project_list'):
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


def _finance_chart(service: DashboardService, report) -> None:
    years = range(service.today().year-2, service.today().year+10)
    # Layered Vega charts can retain their old named dataset when only Arrow data
    # changes. Recreate this chart for different values, without rerunning the shell.
    chart_revision = sha256(repr((years.start, tuple(sorted(report.budget.totals.items())))).encode()).hexdigest()[:16]
    values = pd.DataFrame([{'date': f'{year}-01-01', 'budget': report.budget.totals.get(year) / 100
                            if year in report.budget.totals else None,
                            'series': _label('approved_budget')} for year in years])
    values['segment'] = values['budget'].isna().cumsum().astype(str)
    st.vega_lite_chart(values, {
        'name': 'dashboard_finance_' + chart_revision,
        'layer': [
            {'mark': {'type': 'line', 'point': {'filled': True}},
             'encoding': {'detail': {'field': 'segment', 'type': 'nominal'},
                          'x': {'field': 'date', 'type': 'temporal', 'title': _label('year'),
                                'scale': {'domain': [f'{years.start}-01-01', f'{years.stop}-01-01']},
                                'axis': {'format': '%Y', 'labelAngle': 0,
                                         'values': [f'{year}-01-01' for year in years]}},
                          'y': {'field': 'budget', 'type': 'quantitative', 'title': _label('euros')},
                          'color': {'field': 'series', 'type': 'nominal', 'title': None,
                                    'scale': {'range': ['#C41039']}, 'legend': {'orient': 'top-right','direction':'horizontal'}},
                          'tooltip': [{'field': 'date', 'type': 'temporal', 'title': _label('year'), 'format': '%Y'},
                                      {'field': 'budget', 'type': 'quantitative', 'title': _label('euros'), 'format': ',.2f'}]}},
            {'data': {'values': [{'today': service.today().isoformat()}]},
             'mark': {'type': 'rule', 'color': '#23934c', 'strokeDash': [6, 4], 'strokeWidth': 2},
             'encoding': {'x': {'field': 'today', 'type': 'temporal'},
                          'tooltip': [{'field': 'today', 'type': 'temporal', 'title': _label('today'), 'format': '%d/%m/%Y'}]}}
        ]}, height=260, key='dashboard_finance_' + chart_revision)


def _planning_jump(service: DashboardService, ids: tuple[int, ...], quarter: str) -> None:
    projects = service.consuming_projects(list(ids), quarter)
    if not projects:
        st.info(_label('no_consumers'))
        return
    st.session_state['dashboard_planning_projects'] = projects
    st.session_state['nav_redirect'] = PAGE_PLANNING
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
        finance, issues = st.columns([8, 1.5], vertical_alignment='center')
        with finance:
            st.subheader(_label('finance_overview'))
            if _source(report):
                _finance_chart(service, report)
        with issues, st.container(border=True, key='dashboard_issue_card'):
            icon_color = '#df8b16' if report.issue_count else '#23934c'
            text_color = '#df8b16' if report.issue_count else '#000000'
            st.html(f'<style>.st-key-dashboard_issue_card{{--issue-icon:{icon_color};--issue-text:{text_color}}}</style>')
            if st.button(_label('active_issues'), icon=':material/warning:', key='dashboard_issue_count', width='stretch',
                         disabled=report.issue_count == 0,
                         help=t('dashboard.issue_count', count=report.issue_count)) and report.issue_count:
                _issues(service, ids)
            st.markdown(f"{report.issue_count} {_label('active_issues')}")
        st.subheader(_label('capacity_overallocation'))
        quarter = resource_chart(_shortages(service, revision, ids), today=service.today().isoformat(),
            year=service.today().year, locale=get_current_locale(), labels={
                'title': _label('capacity_overallocation'), 'overallocationLabel': _label('overallocation'),
                'capacityLabel': _label('total_capacity'), 'goTo': _label('go_to_consumers')})
        if quarter:
            _planning_jump(service, ids, quarter)
    except (AccessDenied, ProjectStorageError, ValueError):
        st.error(_label('unavailable'))
