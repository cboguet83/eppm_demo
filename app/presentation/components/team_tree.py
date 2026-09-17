"""Team hierarchy using the same filtered tree and context menus as resource pools."""

import streamlit as st

from app.application.services.team_capacity import TeamOverview
from app.presentation.components.action_table import TableAction
from app.presentation.components.context_menu import CONTEXT_MENU_CSS
from app.presentation.components.resource_pool_tree import _CSS, _JS


def team_tree(overview: TeamOverview, selected: int, hierarchy_labels: dict[int, str]) -> TableAction | None:
    """Render a bounded leaf-first traversal and validate every returned action."""
    teams = {team.team_id: team for team in overview.teams}
    functions = {function.function_id: function.name for function in overview.functions}
    children: dict[int | None, list[int]] = {}
    for team in teams.values():
        children.setdefault(team.parent_team_id, []).append(team.team_id)
    for parent, siblings in children.items():
        siblings.sort(key=lambda identity: (parent is not None and bool(children.get(identity)),
                                            teams[identity].team_name.casefold(), identity))
    pending = [(identity, 0) for identity in reversed(children.get(None, []))]
    rows = []
    seen: set[int] = set()
    while pending:
        identity, depth = pending.pop()
        if identity in seen:
            raise ValueError('The team hierarchy contains a cycle.')
        seen.add(identity)
        team, detail = teams[identity], overview.capacities[identity]
        rows.append({'id': identity, 'name': team.team_name, 'parent': team.parent_team_id, 'depth': depth,
            'container': bool(children.get(identity)), 'has_children': bool(children.get(identity)),
            'deleted': team.deleted_flag, 'manager': functions.get(team.manager_function_id, '—'),
            'hierarchy_type': hierarchy_labels.get(team.hierarchy_type_id, '—'),
            'assigned_capacity': '' if team.deleted_flag else f'{detail.current_fte:.2f}',
            'mappings': '✓' if detail.members else '',
            'future_exceptions': '✓' if detail.has_future_exceptions else ''})
        pending.extend((child, depth + 1) for child in reversed(children.get(identity, [])))
    if seen != teams.keys():
        raise ValueError('The team hierarchy has a missing parent or cycle.')
    key = 'team_hierarchy'
    state = st.session_state.get(key, {})
    def select_row() -> None:
        identity = st.session_state[key].get('selected')
        if type(identity) is int and identity in teams:
            st.session_state['selected_team_id'] = identity
    css = _CSS + CONTEXT_MENU_CSS + '''
    .pool-row,.tree-columns {grid-template-columns:minmax(240px,1fr) 240px 150px 180px 140px 230px; min-width:1220px;}
    '''
    component = st.components.v2.component('eppm_team_tree', html='<div class="pool-tree"></div>', css=css, js=_JS)
    result = component(data={'kind': 'team', 'rows': rows, 'selected': selected,
        'columns': [('name', 'Team'), ('manager', 'Manager function'), ('hierarchy_type', 'Hierarchy type'),
                    ('assigned_capacity', 'Current Capacity (FTE)'), ('mappings', 'Has Mappings'),
                    ('future_exceptions', 'Has Future Capacity Exceptions')],
        'collapsed': state.get('collapsed', []), 'filters': state.get('filters', {}), 'sort': state.get('sort', {})},
        key=key, width='stretch', height='content', on_action_change=lambda: None, on_selected_change=select_row,
        on_collapsed_change=lambda: None, on_filters_change=lambda: None, on_sort_change=lambda: None)
    event = getattr(result, 'action', None)
    if not isinstance(event, dict) or type(event.get('id')) is not int:
        return None
    identity, action = event['id'], event.get('action')
    if action == 'create_root':
        return TableAction(id=0, action=action) if identity == 0 else None
    if identity not in teams:
        return None
    allowed = {'select', 'undelete'} if teams[identity].deleted_flag else {'select', 'edit', 'create', 'delete'}
    return TableAction(id=identity, action=action) if action in allowed else None
