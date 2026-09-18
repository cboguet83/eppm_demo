"""Function reporting hierarchy using the resource pool tree interaction model."""

import streamlit as st

from app.domain.organization.models import OrgFunction
from app.presentation.components.action_table import TableAction
from app.presentation.components.context_menu import CONTEXT_MENU_CSS
from app.presentation.components.resource_pool_tree import _CSS, _JS


def function_rows(records: list[OrgFunction], type_labels: dict[int, str]) -> list[dict]:
    """Build JSON rows with derived reports and bounded, leaf-first traversal."""
    functions = {item.function_id: item for item in records}
    children: dict[int | None, list[int]] = {}
    for item in records:
        parent = item.manager_function_id if item.manager_function_id in functions else None
        children.setdefault(parent, []).append(item.function_id)
    for siblings in children.values():
        siblings.sort(key=lambda identity: (bool(children.get(identity)), functions[identity].name.casefold(), identity))
    pending = [(identity, 0) for identity in reversed(children.get(None, []))]
    rows, seen = [], set()
    while pending:
        identity, depth = pending.pop()
        if identity in seen:
            raise ValueError('The function hierarchy contains a cycle.')
        seen.add(identity)
        item = functions[identity]
        dual = functions.get(item.dual_manager_function_id)
        rows.append({'id': identity, 'name': item.name,
            'parent': item.manager_function_id if item.manager_function_id in functions else None,
            'depth': depth, 'container': bool(children.get(identity)),
            'has_children': bool(children.get(identity)), 'deleted': item.deleted_flag,
            'hierarchy_level': item.hierarchy_level,
            'has_reports': 'Yes' if any(not functions[child].deleted_flag for child in children.get(identity, [])) else 'No',
            'function_type': type_labels.get(item.function_type_id, '—'),
            'dual_manager': dual.name if dual else '—', 'fte_percentage': item.fte_percentage})
        pending.extend((child, depth + 1) for child in reversed(children.get(identity, [])))
    if seen != functions.keys():
        raise ValueError('The function hierarchy contains a cycle.')
    return rows


def function_tree(records: list[OrgFunction], selected: int, type_labels: dict[int, str]) -> TableAction | None:
    """Render shared filters and menus, validating actions against visible records."""
    functions = {item.function_id: item for item in records}
    key = 'function_hierarchy'
    state = st.session_state.get(key, {})
    def select_row() -> None:
        identity = st.session_state[key].get('selected')
        if type(identity) is int and identity in functions:
            st.session_state['selected_function_id'] = identity
    component = st.components.v2.component('eppm_function_tree', html='<div class="pool-tree"></div>',
        css=_CSS + CONTEXT_MENU_CSS + '.pool-row,.tree-columns{grid-template-columns:minmax(240px,1fr) 140px 120px 200px 220px 100px;min-width:1020px}', js=_JS)
    result = component(data={'kind': 'function', 'rows': function_rows(records, type_labels), 'selected': selected,
        'columns': [('name', 'Function Title'), ('hierarchy_level', 'Hierarchy Level'),
                    ('has_reports', 'Has Reports'), ('function_type', 'Function Type'),
                    ('dual_manager', 'Dual Manager'), ('fte_percentage', 'FTE %')],
        'collapsed': state.get('collapsed', []), 'filters': state.get('filters', {}), 'sort': state.get('sort', {})},
        key=key, width='stretch', height='content', on_action_change=lambda: None, on_selected_change=select_row,
        on_collapsed_change=lambda: None, on_filters_change=lambda: None, on_sort_change=lambda: None)
    event = getattr(result, 'action', None)
    if not isinstance(event, dict) or type(event.get('id')) is not int:
        return None
    identity, action = event['id'], event.get('action')
    if action == 'create_root':
        return TableAction(id=0, action=action) if identity == 0 else None
    if identity not in functions:
        return None
    allowed = {'select', 'undelete'} if functions[identity].deleted_flag else {'select', 'edit', 'create', 'delete'}
    return TableAction(id=identity, action=action) if action in allowed else None
