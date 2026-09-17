"""Expandable pool hierarchy with selection and contextual editing actions."""

import streamlit as st

from app.domain.resources.hierarchy import PoolHierarchy
from app.presentation.components.action_table import TableAction
from app.presentation.components.context_menu import CONTEXT_MENU_CSS


_CSS = """
.pool-tree {font:inherit; border:1px solid var(--st-border-color); border-radius:8px;}
.tree-scroll {max-height:460px; overflow:auto; padding:6px;}
.pool-row {display:grid; grid-template-columns:minmax(240px,1fr) 110px 120px 130px 150px 150px 140px 185px;
    align-items:center; gap:8px; padding:4.2px 10px; box-sizing:border-box;
    border-radius:5px; cursor:pointer; min-height:36.4px; outline-offset:-2px;}
.pool-row.container {font-weight:700; background:#f1f3f5; color:#263238;}
.pool-identity {display:flex; align-items:center; min-width:0;}
.tree-columns {display:grid; grid-template-columns:minmax(240px,1fr) 110px 120px 130px 150px 150px 140px 185px;
    gap:8px; padding:8px 10px; font-size:12px; font-weight:600; position:sticky; top:0;
    background:var(--st-background-color); z-index:1;}
.pool-row,.tree-columns {min-width:1300px;}
.tree-columns input {display:block; box-sizing:border-box; width:100%; min-width:0; margin-top:6px;
    font:inherit; font-weight:400; padding:5px; border:1px solid var(--st-border-color);
    border-radius:4px; color:var(--st-text-color); background:var(--st-background-color);}
.tree-columns .filter-button {display:flex; justify-content:space-between; align-items:center;
    font:inherit; font-size:12px; white-space:nowrap; width:100%; padding:0; border:0; text-align:left;}
.filter-panel {padding:12px; width:280px;}
.filter-options {max-height:220px; overflow:auto; margin:8px 0;}
.filter-option {display:flex; align-items:center; gap:8px; padding:4px 0; font-weight:400;}
.filter-search {width:100%; box-sizing:border-box; padding:6px;}
.filter-actions {display:flex; gap:6px;}
.pool-tags {overflow:hidden; text-overflow:ellipsis;}
.pool-row:hover {background:var(--st-secondary-background-color);}
.pool-row[aria-selected=true] {background:var(--st-secondary-background-color);
    box-shadow:inset 3px 0 var(--st-primary-color);}
.pool-row.container[aria-selected=true] {background:#f1f3f5;}
.pool-name {flex:1; overflow-wrap:anywhere;}
.pool-meta {font-size:13px; opacity:.75; white-space:nowrap;}
.pool-meta.capacity-exceeded {color:#c62828; opacity:1; font-weight:700;}
.pool-warning {color:#c62828; margin-left:6px; flex-shrink:0;}
.pool-deleted {font-size:12px; margin-left:8px; padding:2px 6px; border:1px solid currentColor; border-radius:4px;}
.tree-toggle {display:inline-flex; justify-content:center; width:22px; flex-shrink:0;}
.pool-row:focus-visible {outline:2px solid var(--st-primary-color);}
"""

_JS = r"""
export default function({data, parentElement, setTriggerValue, setStateValue}) {
    const root = parentElement.querySelector('.pool-tree');
    const scrollTop = root.querySelector('.tree-scroll')?.scrollTop || 0;
    root.replaceChildren();
    let menu = null;
    const collapsed = new Set(data.collapsed || []);
    const filters = data.filters || {};
    const activeFilters = Object.values(filters).some(value => Array.isArray(value));
    const fields = ['name','pool_type','hierarchy_type','tags','capacity','assigned_capacity','mappings','peak_demand'];
    const matches = new Set(data.rows.filter(row => fields.every(field =>
        !Array.isArray(filters[field]) || filters[field].includes(String(row[field]))
    )).map(row => row.id));
    const visible = new Set(matches);
    const byId = new Map(data.rows.map(row => [row.id,row]));
    for (const id of matches) {
        let parent = byId.get(id).parent;
        while (parent !== null && !visible.has(parent)) {visible.add(parent); parent = byId.get(parent)?.parent ?? null;}
    }
    const closeMenu = (clear = true) => {menu?.remove(); menu = null; if (clear) delete root.dataset.context;};
    const highlight = row => root.querySelectorAll('[role=treeitem]').forEach(item =>
        item.setAttribute('aria-selected', String(Number(item.dataset.id) === row.id)));
    const emit = (row, action) => {
        closeMenu();
        root.querySelectorAll('[role=treeitem]').forEach(item =>
            item.setAttribute('aria-selected', String(Number(item.dataset.id) === row.id)));
        setTriggerValue('action', {id:row.id, action});
    };
    const showMenu = (event, row, item, restoring = false) => {
        event.preventDefault(); event.stopPropagation(); closeMenu();
        if (row.id) highlight(row);
        root.dataset.context = JSON.stringify({id:row.id,x:event.clientX,y:event.clientY});
        if (!restoring && row.id && row.id !== data.selected) setStateValue('selected',row.id);
        menu = document.createElement('div'); menu.className = 'context-menu';
        menu.setAttribute('role', 'menu'); menu.setAttribute('aria-label', row.name);
        const heading = document.createElement('div'); heading.className = 'context-menu-header';
        heading.textContent = row.name; menu.appendChild(heading);
        let actions = [['create_root','Create pool']];
        if (row.id) actions = row.deleted ? [['undelete','Undelete pool']]
            : [['edit','Edit pool'], ['create','Create pool'], ['gantt','Show consuming projects in Gantt'], ['delete','Delete pool']];
        if (row.id && !row.container && !row.deleted) actions.splice(2,0,['map','Map employees or teams']);
        for (const [action, label] of actions) {
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
    const tree = document.createElement('div'); tree.className = 'tree-scroll';
    tree.tabIndex = 0;
    tree.setAttribute('role','tree'); tree.setAttribute('aria-label','Resource pools');
    tree.oncontextmenu = event => showMenu(event,{id:0,name:'Resource pools',container:true},tree);
    tree.onkeydown = event => {
        if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
            const rect = tree.getBoundingClientRect();
            showMenu({preventDefault:()=>event.preventDefault(),stopPropagation:()=>event.stopPropagation(),
                clientX:rect.left+20,clientY:rect.top+40},{id:0,name:'Resource pools',container:true},tree);
        }
    };
    const header = document.createElement('div'); header.className = 'tree-columns';
    const openFilter = (event, field, label) => {
        event.stopPropagation(); closeMenu();
        menu = document.createElement('div'); menu.className = 'context-menu filter-panel';
        menu.setAttribute('role','dialog'); menu.setAttribute('aria-label',`Filter ${label}`);
        const numeric = ['capacity','assigned_capacity','peak_demand'].includes(field);
        const values = [...new Set(data.rows.map(row => String(row[field])))].sort((a,b) => numeric ? Number(a)-Number(b) : a.localeCompare(b));
        const selected = new Set(Array.isArray(filters[field]) ? filters[field] : values);
        const button = (label, action) => {
            const result = document.createElement('button'); result.className = 'context-menu-item';
            result.textContent = label; result.onclick = action; return result;
        };
        for (const [label,descending] of [['Sort ascending',false],['Sort descending',true]]) {
            menu.appendChild(button(label,()=>{closeMenu();setStateValue('sort',{field,descending});}));
        }
        const search = document.createElement('input'); search.type = 'search'; search.className = 'filter-search';
        search.placeholder = 'Search'; search.setAttribute('aria-label','Search filter values'); menu.appendChild(search);
        const all = document.createElement('label'); all.className = 'filter-option';
        const allCheck = document.createElement('input'); allCheck.type = 'checkbox';
        all.append(allCheck,document.createTextNode('Select all')); menu.appendChild(all);
        const options = document.createElement('div'); options.className = 'filter-options'; menu.appendChild(options);
        const renderOptions = () => {
            options.replaceChildren();
            const shown = values.filter(value => value.toLocaleLowerCase().includes(search.value.toLocaleLowerCase()));
            allCheck.checked = shown.every(value => selected.has(value));
            allCheck.indeterminate = !allCheck.checked && shown.some(value=>selected.has(value));
            for (const value of shown) {
                const label = document.createElement('label'); label.className = 'filter-option';
                const check = document.createElement('input'); check.type = 'checkbox'; check.checked = selected.has(value);
                check.onchange = () => {if(check.checked) selected.add(value); else selected.delete(value); renderOptions();};
                label.append(check,document.createTextNode(value || '(Blanks)')); options.appendChild(label);
            }
        };
        search.oninput = renderOptions;
        allCheck.onchange = () => {
            for (const value of values.filter(value=>value.toLocaleLowerCase().includes(search.value.toLocaleLowerCase()))) {
                if(allCheck.checked) selected.add(value); else selected.delete(value);
            }
            renderOptions();
        };
        renderOptions();
        const actions = document.createElement('div'); actions.className = 'filter-actions';
        actions.append(button('Apply',()=>{const next={...filters}; next[field]=[...selected]; closeMenu();setStateValue('filters',next);}),
                       button('Clear filter',()=>{const next={...filters};delete next[field];closeMenu();setStateValue('filters',next);}),
                       button('Cancel',()=>closeMenu()));
        menu.appendChild(actions); root.appendChild(menu);
        const rect = event.currentTarget.getBoundingClientRect();
        menu.style.left = Math.max(10,Math.min(rect.left,window.innerWidth-menu.offsetWidth-10))+'px';
        menu.style.top = Math.max(10,Math.min(rect.bottom,window.innerHeight-menu.offsetHeight-10))+'px';
        search.focus();
    };
    for (const [index,text] of ['Pool','Pool type','Hierarchy type','Tags','Pool Capacity (FTE)','Current Capacity (FTE)','Has Mappings','Future Peak Demand (FTE)'].entries()) {
        const cell = document.createElement('span');
        const button = document.createElement('button'); button.className = 'context-menu-item filter-button';
        button.setAttribute('aria-label',`Filter ${text}`); button.setAttribute('aria-haspopup','dialog');
        button.textContent = text + (Array.isArray(filters[fields[index]]) ? ' ▾ ●' : ' ▾');
        if (index === 5) button.title = "Today's capacity after employee availability exceptions, or pool capacity exceptions when unmapped.";
        if (index === 6) button.title = 'A check mark indicates direct employee or team mappings on a leaf pool.';
        if (index === 7) button.title = 'Maximum required FTE from today onward for the selected project statuses.';
        button.onclick = event => openFilter(event,fields[index],text);
        cell.appendChild(button); header.appendChild(cell);
    }
    tree.appendChild(header);
    const children = new Map();
    for (const row of data.rows) {if (!children.has(row.parent)) children.set(row.parent,[]); children.get(row.parent).push(row);}
    const sort = data.sort || {};
    if (fields.includes(sort.field)) for (const siblings of children.values()) siblings.sort((a,b)=> {
        const compare = ['capacity','assigned_capacity','peak_demand'].includes(sort.field)
            ? Number(a[sort.field])-Number(b[sort.field]) : String(a[sort.field]).localeCompare(String(b[sort.field]));
        return sort.descending ? -compare : compare;
    });
    const orderedRows = []; const pending = [...(children.get(null) || [])].reverse();
    while(pending.length) {const row = pending.pop();orderedRows.push(row);pending.push(...[...(children.get(row.id)||[])].reverse());}
    let hiddenBelow = null;
    for (const row of orderedRows) {
        if (!visible.has(row.id)) continue;
        if (!activeFilters && hiddenBelow !== null && row.depth > hiddenBelow) continue;
        hiddenBelow = null;
        const item = document.createElement('div'); item.className = 'pool-row'; item.tabIndex = 0;
        item.dataset.id = row.id; item.setAttribute('role','treeitem');
        item.setAttribute('aria-label',row.name + (row.deleted ? ' (Deleted)' : '')); item.setAttribute('aria-level',row.depth+1);
        item.setAttribute('aria-selected',String(row.id === data.selected));
        if (row.container) item.classList.add('container');
        const identity = document.createElement('span'); identity.className = 'pool-identity';
        identity.style.paddingLeft = (row.depth*24)+'px';
        const toggle = document.createElement('span'); toggle.className = 'tree-toggle';
        toggle.setAttribute('aria-hidden','true'); toggle.textContent = row.has_children ? (collapsed.has(row.id) && !activeFilters ? '▸' : '▾') : '·';
        const changeExpanded = () => {
            root.dataset.focusPool = row.id;
            if (collapsed.has(row.id)) collapsed.delete(row.id); else collapsed.add(row.id);
            setStateValue('collapsed',[...collapsed]);
        };
        if (row.has_children) {
            item.setAttribute('aria-expanded',String(activeFilters || !collapsed.has(row.id)));
            toggle.onclick = event => {event.stopPropagation(); changeExpanded();};
            if (collapsed.has(row.id)) hiddenBelow = row.depth;
        }
        const label = document.createElement('span'); label.className = 'pool-name'; label.textContent = row.name;
        identity.append(toggle,label); item.appendChild(identity);
        if (row.deleted) {
            const badge = document.createElement('span'); badge.className = 'pool-deleted';
            badge.textContent = 'Deleted'; identity.appendChild(badge);
        }
        if (row.current_exceeded || row.peak_exceeded) {
            const warning = document.createElement('span'); warning.className = 'pool-warning';
            warning.textContent = '\u26a0'; warning.setAttribute('role','img');
            warning.title = [row.current_exceeded ? 'Current mappedcapacity exceeds pool capacity. Verify teams and employess mapping to this pool' : '',
                row.peak_exceeded ? 'Future peak demand exceeds available capacity on a peak-demand date.' : ''].filter(Boolean).join(' ');
            warning.setAttribute('aria-label',warning.title); label.appendChild(warning);
        }
        for (const [index,value] of [row.pool_type,row.hierarchy_type,row.tags,row.capacity,row.assigned_capacity,row.mappings,row.peak_demand].entries()) {
            const cell = document.createElement('span'); cell.className = 'pool-meta';
            if ((index === 4 && row.current_exceeded) || (index === 6 && row.peak_exceeded)) {
                cell.classList.add('capacity-exceeded');
            }
            if (index === 2) {cell.classList.add('pool-tags'); cell.title = value;}
            if (index === 5) {cell.style.fontWeight = '900';}
            cell.textContent = value; item.appendChild(cell);
        }
        item.children[5].title = "Today's capacity after employee availability exceptions, or pool capacity exceptions when unmapped.";
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
            } else if (row.has_children && ((event.key === 'ArrowRight' && collapsed.has(row.id)) ||
                       (event.key === 'ArrowLeft' && !collapsed.has(row.id)))) {event.preventDefault(); changeExpanded();}
        };
        tree.appendChild(item);
    }
    if (!visible.size) {
        const empty = document.createElement('p');
        empty.textContent = data.rows.length ? 'No pools match these filters.' : 'No pools yet. Right-click here to create a pool.';
        tree.appendChild(empty);
    }
    root.appendChild(tree);
    tree.scrollTop = scrollTop;
    if (root.dataset.focusPool) {
        tree.querySelector(`[data-id="${root.dataset.focusPool}"]`)?.focus({preventScroll:true});
        delete root.dataset.focusPool;
    }
    if (root.dataset.context) {
        const context = JSON.parse(root.dataset.context); const row = byId.get(context.id);
        const item = tree.querySelector(`[data-id="${context.id}"]`);
        if (row && item) showMenu({preventDefault:()=>{},stopPropagation:()=>{},clientX:context.x,clientY:context.y},row,item,true);
    }
    const escape = event => {if(event.key === 'Escape') closeMenu();};
    document.addEventListener('keydown',escape);
    const outside = event => {if (menu && !event.composedPath().includes(menu)) closeMenu();};
    document.addEventListener('pointerdown',outside);
    document.addEventListener('scroll',closeMenu,true);
    return () => {
        document.removeEventListener('pointerdown',outside);
        document.removeEventListener('scroll',closeMenu,true); document.removeEventListener('keydown',escape); closeMenu(false);
    };
}
"""


def resource_pool_tree(
    hierarchy: PoolHierarchy, capacities: dict[int, float], selected: int,
    *, assigned_capacities: dict[int, float] | None = None,
    pool_types: dict[int, str] | None = None,
    hierarchy_types: dict[int, str] | None = None,
    tags: dict[int, list[str]] | None = None,
    peak_demands: dict[int, float] | None = None,
    peak_capacities: dict[int, float] | None = None,
    mapping_types: dict[int, set[str]] | None = None,
) -> TableAction | None:
    """Render a validated forest and accept actions only for existing pool IDs.

    Args:
        hierarchy: Validated pool snapshot used for iterative tree ordering.
        capacities: Effective capacity of active leaf pools only.
        selected: Pool currently inspected by the surrounding page.
        assigned_capacities: Today's current capacity of active leaf pools.
        pool_types: Localized labels by pool type ID.
        hierarchy_types: Localized labels by hierarchy type ID.
        tags: Pool-tag labels by pool ID.
        peak_demands: Peak required daily demand from today onward for selected statuses.
        peak_capacities: Available capacity on peak-demand dates, including exceptions.
        mapping_types: Direct mapping target types by pool ID.

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
        pool = hierarchy.pools[identity]
        container = bool(children) if pool.deleted_flag else any(
            not hierarchy.pools[child].deleted_flag for child in children)
        calculated = not container and not pool.deleted_flag
        targets = (mapping_types or {}).get(identity, set())
        mapping_label = '✓' if calculated and targets & {'employee', 'team'} else ''
        nominal_capacity = capacities.get(identity, 0)
        current_capacity = (assigned_capacities or {}).get(identity, 0)
        peak_demand = (peak_demands or {}).get(identity, 0)
        rows.append({'id': identity, 'name': hierarchy.pools[identity].name, 'depth': depth,
                     'current_exceeded': calculated and current_capacity > nominal_capacity,
                     'peak_exceeded': calculated and peak_demand > (peak_capacities or {}).get(identity, nominal_capacity),
                     'deleted': pool.deleted_flag, 'has_children': bool(children),
                     'mappings': mapping_label,
                     'parent': hierarchy.pools[identity].parent_pool_id,
                     'peak_demand': f'{peak_demand:.2f}' if calculated else '',
                     'tags': ', '.join((tags or {}).get(identity, [])),
                     'container': container, 'capacity': f'{nominal_capacity:.2f}' if calculated else '',
                     'assigned_capacity': f'{current_capacity:.2f}' if calculated else '',
                     'pool_type': (pool_types or {}).get(hierarchy.pools[identity].pool_type_id, '—'),
                     'hierarchy_type': (hierarchy_types or {}).get(hierarchy.pools[identity].hierarchy_type_id, '—')})
        pending.extend((child, depth + 1) for child in order(children))
    key = 'resource_pool_tree'
    state = st.session_state.get(key, {})
    component = st.components.v2.component(
        'eppm_resource_pool_tree', html='<div class="pool-tree"></div>',
        css=_CSS + CONTEXT_MENU_CSS, js=_JS,
    )
    def select_row() -> None:
        selected_id = st.session_state[key].get('selected')
        if type(selected_id) is int and selected_id in hierarchy.pools:
            st.session_state['sb_selected_resource_pool'] = selected_id

    result = component(data={'rows': rows, 'selected': selected, 'collapsed': state.get('collapsed', []),
                             'filters': state.get('filters', {}), 'sort': state.get('sort', {})},
                       key=key, width='stretch', height='content',
                       on_action_change=lambda: None, on_collapsed_change=lambda: None, on_filters_change=lambda: None, on_sort_change=lambda: None, on_selected_change=select_row)
    event = getattr(result, 'action', None)
    if not isinstance(event, dict) or event.get('action') not in ('select', 'edit', 'create', 'gantt', 'map', 'create_root', 'delete', 'undelete'):
        return None
    identity = event.get('id')
    if event['action'] == 'create_root':
        return TableAction(id=0, action='create_root') if type(identity) is int and identity == 0 else None
    if type(identity) is not int or identity not in hierarchy.pools:
        return None
    if hierarchy.pools[identity].deleted_flag and event['action'] not in ('select', 'undelete'):
        return None
    if event['action'] == 'undelete' and not hierarchy.pools[identity].deleted_flag:
        return None
    if event['action'] == 'map' and any(not hierarchy.pools[child].deleted_flag for child in hierarchy.children.get(identity, [])):
        return None
    return TableAction(id=identity, action=event['action'])
