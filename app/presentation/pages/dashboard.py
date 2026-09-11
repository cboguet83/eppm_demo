"""Fragment-local portfolio dashboard and shared read-only allocated-budget view."""

import pandas as pd
import streamlit as st

from app.application.exceptions import ProjectStorageError
from app.application.services.dashboard import DashboardService
from app.domain.access.models import AccessDenied
from app.domain.finance import euro_text
from app.presentation.components.action_table import action_table
from app.presentation.components.dialog import dialog
from app.presentation.components.authorized_cache import authorized_cache
from app.presentation.i18n import get_current_locale, t


def _label(key: str) -> str:
    return t('dashboard.' + key)


@authorized_cache(show_spinner=False, max_entries=32, ttl=300)
def _catalog(_service: DashboardService, revision: tuple):
    return _service.catalog()


@authorized_cache(show_spinner=False, max_entries=128, ttl=300)
def _report(_service: DashboardService, revision: tuple, ids: tuple[int, ...]):
    return _service.report(list(ids))


@authorized_cache(show_spinner=False, max_entries=64, ttl=300)
def _shortages(_service: DashboardService, revision: tuple, ids: tuple[int, ...]):
    return _service.shortages(list(ids))


def _reset_page() -> None:
    st.session_state['dashboard_offset'] = 0


def _clear() -> None:
    for key in list(st.session_state):
        if key.startswith('dashboard_filter_'):
            del st.session_state[key]
    st.session_state['dashboard_flex_fields'] = []
    st.session_state['dashboard_match'] = 'Any'
    _reset_page()


def _source(report) -> bool:
    if report.approved is None:
        st.info(_label('no_approved'))
        return False
    st.caption(t('dashboard.source', number=report.approved.number, name=report.approved.name))
    if report.budget.unmatched:
        st.warning(t('dashboard.unmatched', codes=', '.join(report.budget.unmatched)))
    return True


def render_project_budget(project_id: int, service: DashboardService) -> None:
    """Render the same rounded WBS/year shares used in dashboard totals."""
    st.subheader(_label('budget'))
    try:
        report = _report(service, service.revision(), (project_id,))
        if not _source(report):
            return
        years = range(service.today().year-5, service.today().year+15)
        rows = [{t('wbs.code'): share.code, _label('allocation'): f'{share.percentage}%',
                 **{str(year): euro_text(values[year]) if year in values else None for year in years}}
                for share, values in report.budget.rows]
        if not rows:
            st.info(_label('no_wbs'))
            return
        rows.append({t('wbs.code'): _label('total'), _label('allocation'): '',
                     **{str(year): euro_text(report.budget.totals[year]) if year in report.budget.totals else None for year in years}})
        st.dataframe(pd.DataFrame(rows), hide_index=True, height=min(440, 40+35*len(rows)),
                     column_config={t('wbs.code'): st.column_config.TextColumn(pinned=True)})
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
    fixed = ('level3', 'level4', 'team', 'manager')
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

    columns = st.columns(5, vertical_alignment='bottom')
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


def _projects(projects: list[dict]) -> None:
    total = len(projects)
    offset = min(st.session_state.get('dashboard_offset', 0), max(0, (total-1)//5*5))
    st.caption(t('dashboard.matching', count=total))
    rows = [{_label('project'): row['name'], _label('mail_code'): ', '.join(row['fields'].get('PRM_001', [])),
             _label('phase'): ', '.join(row['fields'].get('PRM_008', [])),
             _label('priority'): ', '.join(row['fields'].get('PRM_027', []))} for row in projects[offset:offset+5]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, height=40+35*min(5, total))
    previous, current, following = st.columns([1, 5, 1])
    previous.button(_label('previous'), disabled=offset == 0, key='dashboard_previous',
                    on_click=lambda: st.session_state.update(dashboard_offset=max(0, offset-5)))
    current.caption(t('dashboard.page', page=offset//5+1, pages=max(1, (total+4)//5)))
    following.button(_label('next'), disabled=offset+5 >= total, key='dashboard_next',
                     on_click=lambda: st.session_state.update(dashboard_offset=offset+5))


@st.fragment
def render_dashboard(service: DashboardService) -> None:
    """Update filters, five-row pages and charts independently of the application shell."""
    st.header(_label('title'))
    try:
        revision = service.revision()
        catalog = _catalog(service, revision)
        filters, match_all = _filters(service, catalog)
        projects = service.filtered(catalog, filters, match_all)
        _projects(projects)
        if not projects:
            st.info(_label('no_projects'))
            return
        ids = tuple(row['id'] for row in projects)
        report = _report(service, revision, ids)
        st.subheader(_label('budget'))
        if _source(report):
            values = pd.DataFrame([{'year': year, 'budget': report.budget.totals.get(year) / 100 if year in report.budget.totals else None}
                                   for year in range(service.today().year-5, service.today().year+15)])
            values['segment'] = values['budget'].isna().cumsum().astype(str)
            st.vega_lite_chart(values, {
                'mark': {'type': 'line', 'point': {'filled': True, 'color': '#C41039'}, 'color': '#C41039'},
                'encoding': {'detail': {'field': 'segment', 'type': 'nominal'}, 'x': {'field': 'year', 'type': 'ordinal', 'title': _label('year'), 'axis': {'labelAngle': 0}},
                             'y': {'field': 'budget', 'type': 'quantitative', 'title': _label('euros')},
                             'tooltip': [{'field': 'year', 'type': 'ordinal', 'title': _label('year')},
                                         {'field': 'budget', 'type': 'quantitative', 'title': _label('euros'), 'format': ',.2f'}]}}, height=260)
        st.subheader(_label('shortfall'))
        shortage = _shortages(service, revision, ids)
        values = pd.DataFrame([{'quarter': key, 'fte': value} for key, value in shortage.items()])
        st.vega_lite_chart(values, {
            'mark': {'type': 'bar', 'color': '#7851A9'},
            'encoding': {'x': {'field': 'quarter', 'type': 'ordinal', 'title': _label('quarter'),
                               'axis': {'labelExpr': "indexof(datum.label, 'Q1') >= 0 ? datum.label : ''", 'labelAngle': -45}},
                         'y': {'field': 'fte', 'type': 'quantitative', 'title': _label('fte'),
                               'axis': {'format': '~g'}, 'scale': {'domainMin': 0, 'domainMax': max(1, *shortage.values())}},
                         'tooltip': [{'field': 'quarter', 'type': 'ordinal', 'title': _label('quarter')},
                                     {'field': 'fte', 'type': 'quantitative', 'title': _label('fte'), 'format': ',.3f'}]}}, height=240)
        if st.button(t('dashboard.issue_count', count=report.issue_count), key='dashboard_issue_count', icon=':material/report:'):
            _issues(service, ids)
    except (AccessDenied, ProjectStorageError):
        st.error(_label('unavailable'))
