"""Fragment-local portfolio dashboard and shared read-only allocated-budget view."""

from hashlib import sha256

import pandas as pd
import streamlit as st

from app.application.exceptions import ProjectStorageError
from app.application.services.dashboard import DashboardService
from app.domain.access.models import AccessDenied
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
    projects = service.filtered(_catalog(service, revision), filters, match_all)
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
                        len(projects), offset, token, _label('loading'))


def _finance_chart(service: DashboardService, report) -> None:
    years = range(service.today().year-5, service.today().year+15)
    values = pd.DataFrame([{'date': f'{year}-01-01', 'budget': report.budget.totals.get(year) / 100
                            if year in report.budget.totals else None,
                            'series': _label('approved_budget')} for year in years])
    values['segment'] = values['budget'].isna().cumsum().astype(str)
    st.vega_lite_chart(values, {
        'layer': [
            {'mark': {'type': 'line', 'point': {'filled': True}},
             'encoding': {'detail': {'field': 'segment', 'type': 'nominal'},
                          'x': {'field': 'date', 'type': 'temporal', 'title': _label('year'),
                                'scale': {'domain': [f'{years.start}-01-01', f'{years.stop}-01-01']},
                                'axis': {'format': '%Y', 'labelAngle': 0,
                                         'values': [f'{year}-01-01' for year in years]}},
                          'y': {'field': 'budget', 'type': 'quantitative', 'title': _label('euros')},
                          'color': {'field': 'series', 'type': 'nominal', 'title': None,
                                    'scale': {'range': ['#C41039']}, 'legend': {'orient': 'bottom'}},
                          'tooltip': [{'field': 'date', 'type': 'temporal', 'title': _label('year'), 'format': '%Y'},
                                      {'field': 'budget', 'type': 'quantitative', 'title': _label('euros'), 'format': ',.2f'}]}},
            {'data': {'values': [{'today': service.today().isoformat()}]},
             'mark': {'type': 'rule', 'color': '#23934c', 'strokeDash': [6, 4], 'strokeWidth': 2},
             'encoding': {'x': {'field': 'today', 'type': 'temporal'},
                          'tooltip': [{'field': 'today', 'type': 'temporal', 'title': _label('today'), 'format': '%d/%m/%Y'}]}}
        ]}, height=260)


def _planning_jump(service: DashboardService, ids: tuple[int, ...], quarter: str) -> None:
    projects = service.consuming_projects(list(ids), quarter)
    if not projects:
        st.info(_label('no_consumers'))
        return
    st.session_state['dashboard_planning_projects'] = projects
    st.session_state['nav_redirect'] = PAGE_PLANNING
    st.rerun()


@st.fragment
def render_dashboard(service: DashboardService) -> None:
    """Update filters, five-row pages and charts independently of the application shell."""
    st.html("<style>.stMainBlockContainer:has(.st-key-dashboard_filter_pool){padding-top:.25rem!important}.st-key-dashboard_issue_count button{background:transparent!important;border:0!important;color:#df8b16!important;font-size:1.2rem}</style>")
    try:
        revision = service.revision()
        catalog = _catalog(service, revision)
        filters, match_all = _filters(service, catalog)
        projects = service.filtered(catalog, filters, match_all)
        # A queued scroll callback can retain an older fragment invocation.
        # Read the latest filter snapshot inside the fragment, not its old arguments.
        st.session_state['dashboard_active_filters'] = (filters, match_all)
        _projects(service)
        if not projects:
            st.info(_label('no_projects'))
            return
        ids = tuple(row['id'] for row in projects)
        report = _report(service, revision, ids)
        title, issues = st.columns([8, 1], vertical_alignment='center')
        title.subheader(_label('finance_overview'))
        with issues:
            if st.button(str(report.issue_count), key='dashboard_issue_count', icon=':material/warning:',
                         help=t('dashboard.issue_count', count=report.issue_count)):
                _issues(service, ids)
        if _source(report):
            _finance_chart(service, report)
        st.subheader(_label('capacity_overallocation'))
        quarter = resource_chart(_shortages(service, revision, ids), today=service.today().isoformat(),
            year=service.today().year, locale=get_current_locale(), labels={
                'title': _label('capacity_overallocation'), 'overallocationLabel': _label('overallocation'),
                'capacityLabel': _label('total_capacity'), 'goTo': _label('go_to_consumers')})
        if quarter:
            _planning_jump(service, ids, quarter)
    except (AccessDenied, ProjectStorageError, ValueError):
        st.error(_label('unavailable'))
