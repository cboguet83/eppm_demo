"""Expandable pool hierarchy with selection and contextual editing actions."""

import streamlit as st

from app.domain.resources.hierarchy import PoolHierarchy
from app.presentation.components.action_table import TableAction
from app.presentation.components.context_menu import CONTEXT_MENU_CSS


_CSS = """
.pool-tree {font:inherit; border:1px solid var(--st-border-color); border-radius:8px;}
.tree-scroll {max-height:460px; overflow:auto; padding:6px;}
.pool-row {display:grid; grid-template-columns:minmax(240px,1fr) 140px 150px 155px 155px;
    align-items:center; gap:8px; padding:4.2px 10px; box-sizing:border-box;
    border-radius:5px; cursor:pointer; min-height:36.4px; outline-offset:-2px;}
.pool-row.container {font-weight:700; background:#f1f3f5; color:#263238;}
.pool-identity {display:flex; align-items:center; min-width:0;}
.tree-columns {display:grid; grid-template-columns:minmax(240px,1fr) 140px 150px 155px 155px;
    gap:8px; padding:8px 10px; font-size:12px; font-weight:600; position:sticky; top:0;
    background:var(--st-background-color); z-index:1;}
.pool-row,.tree-columns {min-width:900px;}
.pool-row:hover {background:var(--st-secondary-background-color);}
.pool-row[aria-selected=true] {background:var(--st-secondary-background-color);
    box-shadow:inset 3px 0 var(--st-primary-color);}
.pool-row.container[aria-selected=true] {background:#f1f3f5;}
.pool-name {flex:1; overflow-wrap:anywhere;}
.pool-meta {font-size:13px; opacity:.75; white-space:nowrap;}
.tree-toggle {display:inline-flex; justify-content:center; width:22px; flex-shrink:0;}
.tree-help {font-size:13px; opacity:.7; padding:10px 16px; border-bottom:1px solid var(--st-border-color);}
.pool-row:focus-visible {outline:2px solid var(--st-primary-color);}
"""

_JS = r"""
export default function({data, parentElement, setTriggerValue, setStateValue}) {
    const root = parentElement.querySelector('.pool-tree');
    const scrollTop = root.querySelector('.tree-scroll')?.scrollTop || 0;
    root.replaceChildren();
    let menu = null;
    const collapsed = new Set(data.collapsed || []);
    const closeMenu = () => {menu?.remove(); menu = null;};
    const emit = (row, action) => {
        closeMenu();
        root.querySelectorAll('[role=treeitem]').forEach(item =>
            item.setAttribute('aria-selected', String(Number(item.dataset.id) === row.id)));
        setTriggerValue('action', {id:row.id, action});
    };
    const showMenu = (event, row, item) => {
        event.preventDefault(); event.stopPropagation(); closeMenu();
        menu = document.createElement('div'); menu.className = 'context-menu';
        menu.setAttribute('role', 'menu'); menu.setAttribute('aria-label', row.name);
        const heading = document.createElement('div'); heading.className = 'context-menu-header';
        heading.textContent = row.name; menu.appendChild(heading);
        for (const [action, label] of [['edit','Edit pool'], ['create','Create child pool']]) {
            const button = document.createElement('button'); button.type = 'button';
            button.className = 'context-menu-item'; button.textContent = label;
            button.setAttribute('role','menuitem'); button.onclick = () => emit(row, action);
            menu.appendChild(button);
        }
        menu.onkeydown = event => {
            const buttons = [...menu.querySelectorAll('button')];
            const index = buttons.indexOf(menu.getRootNode().activeElement);
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault(); buttons[(index + (event.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length].focus();
            }
            if (event.key === 'Escape') {event.preventDefault(); closeMenu(); item.focus();}
        };
        root.appendChild(menu);
        menu.style.left = Math.max(10, Math.min(event.clientX, window.innerWidth-menu.offsetWidth-10))+'px';
        menu.style.top = Math.max(10, Math.min(event.clientY, window.innerHeight-menu.offsetHeight-10))+'px';
        menu.querySelector('button').focus();
    };
    const help = document.createElement('div'); help.className = 'tree-help';
    help.textContent = 'Select a pool to inspect it. Right-click or press Shift+F10 to edit or create a child.';
    root.appendChild(help);
    const tree = document.createElement('div'); tree.className = 'tree-scroll';
    tree.setAttribute('role','tree'); tree.setAttribute('aria-label','Resource pools');
    const header = document.createElement('div'); header.className = 'tree-columns';
    for (const text of ['Pool','Pool type','Hierarchy type','Pool Capacity (FTE)','Mapped Capacity (FTE)']) {
        const cell = document.createElement('span'); cell.textContent = text;
        if (text === 'Mapped Capacity (FTE)') {
            cell.title = 'FTE calculated from the employees mapped in the pool.';
            cell.tabIndex = 0;
        }
        header.appendChild(cell);
    }
    tree.appendChild(header);
    let hiddenBelow = null;
    for (const row of data.rows) {
        if (hiddenBelow !== null && row.depth > hiddenBelow) continue;
        hiddenBelow = null;
        const item = document.createElement('div'); item.className = 'pool-row'; item.tabIndex = 0;
        item.dataset.id = row.id; item.setAttribute('role','treeitem');
        item.setAttribute('aria-label',row.name); item.setAttribute('aria-level',row.depth+1);
        item.setAttribute('aria-selected',String(row.id === data.selected));
        if (row.container) item.classList.add('container');
        const identity = document.createElement('span'); identity.className = 'pool-identity';
        identity.style.paddingLeft = (row.depth*24)+'px';
        const toggle = document.createElement('span'); toggle.className = 'tree-toggle';
        toggle.setAttribute('aria-hidden','true'); toggle.textContent = row.container ? (collapsed.has(row.id) ? '▸' : '▾') : '·';
        const changeExpanded = () => {
            root.dataset.focusPool = row.id;
            if (collapsed.has(row.id)) collapsed.delete(row.id); else collapsed.add(row.id);
            setStateValue('collapsed',[...collapsed]);
        };
        if (row.container) {
            item.setAttribute('aria-expanded',String(!collapsed.has(row.id)));
            toggle.onclick = event => {event.stopPropagation(); changeExpanded();};
            if (collapsed.has(row.id)) hiddenBelow = row.depth;
        }
        const label = document.createElement('span'); label.className = 'pool-name'; label.textContent = row.name;
        identity.append(toggle,label); item.appendChild(identity);
        for (const value of [row.pool_type,row.hierarchy_type,row.capacity,row.assigned_capacity]) {
            const cell = document.createElement('span'); cell.className = 'pool-meta';
            cell.textContent = value; item.appendChild(cell);
        }
        item.lastElementChild.title = 'FTE calculated from the employees mapped to the pool.';
        item.onclick = () => emit(row,'select');
        item.oncontextmenu = event => showMenu(event,row,item);
        item.onkeydown = event => {
            if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
                const rect = item.getBoundingClientRect();
                showMenu({preventDefault:()=>event.preventDefault(),stopPropagation:()=>event.stopPropagation(),
                    clientX:rect.left+30,clientY:rect.bottom},row,item);
            } else if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); emit(row,'select');}
            else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault(); (event.key === 'ArrowDown' ? item.nextElementSibling : item.previousElementSibling)?.focus();
            } else if (row.container && ((event.key === 'ArrowRight' && collapsed.has(row.id)) ||
                       (event.key === 'ArrowLeft' && !collapsed.has(row.id)))) {event.preventDefault(); changeExpanded();}
        };
        tree.appendChild(item);
    }
    root.appendChild(tree);
    tree.scrollTop = scrollTop;
    if (root.dataset.focusPool) {
        tree.querySelector(`[data-id="${root.dataset.focusPool}"]`)?.focus({preventScroll:true});
        delete root.dataset.focusPool;
    }
    const outside = event => {if (menu && !event.composedPath().includes(menu)) closeMenu();};
    document.addEventListener('pointerdown',outside);
    document.addEventListener('scroll',closeMenu,true);
    return () => {
        document.removeEventListener('pointerdown',outside);
        document.removeEventListener('scroll',closeMenu,true); closeMenu();
    };
}
"""


def resource_pool_tree(
    hierarchy: PoolHierarchy, capacities: dict[int, float], selected: int,
    *, assigned_capacities: dict[int, float] | None = None,
    pool_types: dict[int, str] | None = None,
    hierarchy_types: dict[int, str] | None = None,
) -> TableAction | None:
    """Render a validated forest and accept actions only for existing pool IDs.

    Args:
        hierarchy: Validated pool snapshot used for iterative tree ordering.
        capacities: Effective capacity by pool, including container rollups.
        selected: Pool currently inspected by the surrounding page.
        assigned_capacities: Assigned resource capacity, already summed for containers.
        pool_types: Localized labels by pool type ID.
        hierarchy_types: Localized labels by hierarchy type ID.

    Returns:
        A validated selection, edit or child-creation event, when triggered.
    """
    rows = []
    roots = [identity for identity, pool in hierarchy.pools.items() if pool.parent_pool_id is None]
    order = lambda identities: sorted(identities, key=lambda identity: hierarchy.pools[identity].name.casefold(), reverse=True)
    pending = [(identity, 0) for identity in order(roots)]
    while pending:
        identity, depth = pending.pop()
        children = hierarchy.children.get(identity, [])
        rows.append({'id': identity, 'name': hierarchy.pools[identity].name, 'depth': depth,
                     'container': bool(children), 'capacity': f'{capacities.get(identity, 0):.2f}',
                     'assigned_capacity': f'{(assigned_capacities or {}).get(identity, 0):.2f}',
                     'pool_type': (pool_types or {}).get(hierarchy.pools[identity].pool_type_id, '—'),
                     'hierarchy_type': (hierarchy_types or {}).get(hierarchy.pools[identity].hierarchy_type_id, '—')})
        pending.extend((child, depth + 1) for child in order(children))
    key = 'resource_pool_tree'
    state = st.session_state.get(key, {})
    component = st.components.v2.component(
        'eppm_resource_pool_tree', html='<div class="pool-tree"></div>',
        css=_CSS + CONTEXT_MENU_CSS, js=_JS,
    )
    result = component(data={'rows': rows, 'selected': selected, 'collapsed': state.get('collapsed', [])},
                       key=key, width='stretch', height='content',
                       on_action_change=lambda: None, on_collapsed_change=lambda: None)
    event = getattr(result, 'action', None)
    if not isinstance(event, dict) or event.get('action') not in ('select', 'edit', 'create'):
        return None
    identity = event.get('id')
    if type(identity) is not int or identity not in hierarchy.pools:
        return None
    return TableAction(id=identity, action=event['action'])
