"""One filter panel and durable per-session selections across portfolio pages."""

from copy import deepcopy
from collections.abc import Callable

import streamlit as st

from app.application.services.dashboard import DashboardService
from app.application.ports.dashboard import DashboardCatalog
from app.presentation.components.authorized_cache import authorized_cache
from app.presentation.components.checkbox_filter import checkbox_filter
from app.presentation.components.organization_filter_panel import organization_filter_panel
from app.presentation.i18n import get_current_locale, t

_STATE = 'shared_project_filters'


def _label(key: str) -> str:
    return t('dashboard.' + key)


def _filter_key(key: str) -> bool:
    return key.startswith('dashboard_filter_') or key in {'dashboard_flex_fields', 'dashboard_match'}


def remember_filters() -> None:
    """Copy widget values to non-widget state, which survives page cleanup."""
    st.session_state[_STATE] = {
        key: deepcopy(value) for key, value in st.session_state.items()
        if _filter_key(key) and (isinstance(value, list) or key == 'dashboard_match')
    }


def restore_filters() -> None:
    """Restore values removed by Streamlit when another page was rendered."""
    for key, value in st.session_state.get(_STATE, {}).items():
        if key not in st.session_state:
            st.session_state[key] = deepcopy(value)


def reset_page() -> None:
    """Persist selections and reset only page-local browsing/focus state."""
    remember_filters()
    st.session_state['dashboard_offset'] = 0
    st.session_state.pop('dashboard_selected_project', None)
    st.session_state.pop('ms_multi_projects', None)
    st.session_state.pop('active_resource_pool_filter', None)
    st.session_state['portfolio_filter_reset'] = st.session_state.get('portfolio_filter_reset', 0) + 1


def clear_filters() -> None:
    """Reset shared selections to In Progress, leaving other facets unrestricted."""
    st.session_state.pop('dashboard_pending_pool_filter', None)
    for key in list(st.session_state):
        if _filter_key(key):
            del st.session_state[key]
    st.session_state['dashboard_flex_fields'] = []
    st.session_state['dashboard_match'] = 'Any'
    st.session_state['dashboard_filter_status'] = ['In Progress']
    st.session_state['planning_filter_reset'] = st.session_state.get('planning_filter_reset', 0) + 1
    reset_page()


@authorized_cache(show_spinner=False, max_entries=32, ttl=300)
def filter_catalog(_service: DashboardService, revision: tuple) -> DashboardCatalog:
    """Reuse authorized filter source data on each page."""
    return _service.catalog()


def render_project_filters(service: DashboardService, catalog: DashboardCatalog | None = None, *,
                           leading_filter: Callable[[], None] | None = None) -> tuple[dict[str, list[str]], bool]:
    """Render the shared organization and advanced filters with durable state."""
    restore_filters()
    if catalog is None:
        catalog = filter_catalog(service, service.revision())
    st.html('''<style>
        [data-testid="stMainBlockContainer"]:has(.st-key-shared_project_filters_panel) {
            padding-top: .01rem !important;
        }
        [data-testid="stMainBlockContainer"]:has(.st-key-shared_project_filters_panel)
        > [data-testid="stVerticalBlock"] {gap: .2rem;}
        [data-testid="stMainBlockContainer"]:has(.st-key-shared_project_filters_panel)
        > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has(style) {
            display: none;
        }
        .st-key-shared_project_filters_panel[data-testid="stVerticalBlock"] {gap: .5rem !important;}
        .st-key-shared_project_filters_panel [data-testid="stPopoverButton"],
        .st-key-shared_project_filters_panel [data-testid="stPopoverButton"] > button,
        .st-key-shared_project_filters_panel .st-key-dashboard_clear button {
            height:24px !important;min-height:24px !important;padding-block:0 !important;
        }
        .st-key-shared_project_filters_panel [data-testid="stPopoverButton"] p,
        .st-key-shared_project_filters_panel .st-key-dashboard_clear p {
            line-height:22px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
        }
        .st-key-shared_project_filters_panel [data-testid="stIconMaterial"] {font-size:18px;}
        .st-key-shared_project_filters_panel [data-testid="stPopoverButton"] {min-width:0;}
        </style>''')
    with st.container(key='shared_project_filters_panel'):
        result = _draw_filters(service, catalog, leading_filter)
    remember_filters()
    st.session_state['dashboard_active_filters'] = result
    return result


def matching_project_ids(service: DashboardService) -> list[int]:
    """Reauthorize the shared project selection for a lazy page or grid read."""
    filters, match_all = st.session_state.get('dashboard_active_filters', ({'status': ['In Progress']}, False))
    return [row['id'] for row in service.filtered(filter_catalog(service, service.revision()), filters, match_all)]


def _draw_filters(service: DashboardService, catalog: DashboardCatalog,
                  leading_filter: Callable[[], None] | None = None) -> tuple[dict[str, list[str]], bool]:
    if 'dashboard_pending_pool_filter' in st.session_state:
        st.session_state['dashboard_filter_pool'] = st.session_state.pop('dashboard_pending_pool_filter')
    fixed = ('strategic_priority', 'status', 'service', 'division', 'org_team', 'org_manager', 'pool')
    st.session_state.setdefault('dashboard_filter_status', ['In Progress'])
    st.session_state['dashboard_filter_status'] = [
        'In Progress' if value == 'Active' else value
        for value in st.session_state['dashboard_filter_status']
    ]
    fields = {'name': _label('project'),
              'project_manager': _label('manager'),
              '_project_tags': t('planning.flex_filter_project_tags', default='Project tags')}
    for parameter in catalog.parameters:
        label = parameter.get('translations', {}).get(get_current_locale()) or parameter.get('alias') or parameter['param_name']
        fields[parameter['param_id']] = label + (f" ({parameter['param_id']})" if label in fields.values() else '')
    selected_fields = [key for key in st.session_state.get('dashboard_flex_fields', []) if key in fields]
    st.session_state['dashboard_flex_fields'] = selected_fields
    organization = organization_filter_panel(
        lambda upstream, key: service.organization_choices(catalog, upstream, key), catalog.labels,
        prefix='dashboard_filter_', on_change=reset_page,
    )
    active = {key: st.session_state.get('dashboard_filter_' + key, []) for key in (*fixed, *selected_fields)}
    active.update(organization)
    match_all = st.session_state.get('dashboard_match', 'Any') == 'All'
    restricted: dict[str, bool] = {}

    def choose(key: str, label: str) -> None:
        options = service.choices(catalog, active, key, match_all)
        if key == 'status':
            options = sorted((set(options) - {'Active'}) | {'In Progress'}, key=str.casefold)
        state_key = 'dashboard_filter_' + key
        if state_key in st.session_state:
            st.session_state[state_key] = [value for value in st.session_state[state_key] if value in options]
        labels = catalog.labels.get(key, {})
        if key in {'status', 'strategic_priority', 'pool'}:
            active[key] = checkbox_filter(label, options, labels, key=state_key, on_change=reset_page)
            restricted[key] = bool(active[key]) and set(active[key]) != set(options)
        else:
            active[key] = st.multiselect(label, options, key=state_key, on_change=reset_page,
                                         format_func=lambda value: labels.get(value, value) or _label('unassigned'))

    columns = st.columns(([3] if leading_filter else []) + [3, 3, 3, 2, 2], vertical_alignment='top')
    if leading_filter is not None:
        with columns[0]:
            leading_filter()
        columns = columns[1:]
    for column, key in zip(columns, ('status', 'strategic_priority', 'pool')):
        with column:
            choose(key, 'Strategic priority' if key == 'strategic_priority' else _label('project_status') if key == 'status' else _label(key))
    with columns[3], st.container(key='dashboard_advanced_filter'), st.popover(
        _label('advanced_filters'), width='stretch', icon=':material/filter_alt:',
    ):
        chosen = st.multiselect(t('planning.flex_filter_fields', default='Filter fields'), list(fields),
                                format_func=fields.get, key='dashboard_flex_fields', on_change=reset_page)
        match_all = st.segmented_control(t('planning.flex_filter_match_label', default='When several values are selected'),
                                         ['Any', 'All'], default='Any', key='dashboard_match', on_change=reset_page) == 'All'
        for key in chosen:
            choose(key, fields[key])
        active = {key: values for key, values in active.items() if key in fixed or key in chosen}
    with columns[4]:
        st.button(_label('reset_filters'), on_click=clear_filters, width='stretch',
                  icon=':material/filter_alt_off:', key='dashboard_clear')
    advanced_active = any(active.get(key) for key in chosen)
    reset_needed = (set(active['status']) != {'In Progress'} or restricted['pool'] or restricted['strategic_priority']
                    or advanced_active or any(organization.values())
                    or st.session_state.get('dashboard_selected_project') is not None)
    controls = {
        '.st-key-dashboard_filter_status [data-testid="stPopoverButton"]': restricted['status'],
        '.st-key-dashboard_filter_strategic_priority [data-testid="stPopoverButton"]': restricted['strategic_priority'],
        '.st-key-dashboard_filter_pool [data-testid="stPopoverButton"]': restricted['pool'],
        '.st-key-dashboard_advanced_filter [data-testid="stPopoverButton"]': advanced_active,
        '.st-key-dashboard_clear button': reset_needed,
    }
    styles = []
    for selector, is_active in controls.items():
        background = '#C41039' if is_active else 'transparent'
        color = 'white' if is_active else 'var(--st-text-color, #31333f)'
        border = '#C41039' if is_active else 'var(--st-border-color, #cbd5e1)'
        styles.append(f'{selector}{{background:{background}!important;color:{color}!important;'
                      f'border-color:{border}!important}}')
    st.html('<style>' + ''.join(styles) + '</style>')
    return active, match_all
