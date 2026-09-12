"""Streamlit Components v2 project table used by the portfolio overview."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import streamlit as st

from app.presentation.components.context_menu import CONTEXT_MENU_CSS


_TABLE_HTML = '<div id="portfolio-project-table" class="portfolio-project-table"></div>'

_TABLE_CSS = r"""
.portfolio-project-table {
    color: var(--st-text-color);
    font-family: var(--st-font);
    font-size: 0.875rem;
    position: relative;
}
.table-scroll {
    box-sizing: border-box;
    border: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
    border-radius: 0.5rem;
    /* Header + exactly eight 40px rows; scrollbar height is added at mount. */
    height: 364px;
    overflow: auto;
    overflow-anchor: none;
}
table {
    border-collapse: separate;
    border-spacing: 0;
    min-width: 100%;
    table-layout: fixed;
    width: max-content;
}
th, td {
    border-bottom: 1px solid color-mix(in srgb, var(--st-text-color) 12%, transparent);
    padding: 0 0.7rem;
    line-height: 20px;
    text-align: left;
    white-space: nowrap;
    box-sizing: border-box;
    max-width: 320px;
    overflow: hidden;
    text-overflow: ellipsis;
}
td { height: 40px; }
.overallocation-indicator {
    background: transparent;
    border: 0;
    color: var(--st-red-color, #d32f2f);
    cursor: default;
    font: inherit;
    margin-right: 0.4rem;
    padding: 0 0.15rem;
}
.project-context-menu button {display: block; width: 100%; text-align: left;}
.allocation-status {font-size: 0.78rem;}
.allocation-status button {
    background: var(--st-primary-color, #C41039); color: white;
    border: 0; border-radius: 0.3rem; cursor: pointer; padding: 0.35rem 0.5rem;
}
th { height: 44px; }
.virtual-spacer td { padding: 0; border: 0; }
.virtual-spacer, .loading-row { pointer-events: none; }
th {
    background: var(--st-secondary-background-color);
    font-weight: 600;
    position: sticky;
    top: 0;
    z-index: 2;
}
tbody tr {
    cursor: pointer;
    outline: none;
}
tbody tr:hover, tbody tr:focus-visible {
    background: color-mix(in srgb, var(--st-primary-color) 10%, transparent);
}
tbody tr.selected {
    background: color-mix(in srgb, var(--st-primary-color) 16%, transparent);
    box-shadow: inset 3px 0 0 var(--st-primary-color);
}
.header-content {
    align-items: center;
    display: flex;
    gap: 0.35rem;
    justify-content: space-between;
}
.portfolio-project-table .filter-button {
    align-items: center;
    background: transparent !important;
    border-color: transparent !important;
    border: 0;
    border-radius: 0.25rem;
    color: var(--st-text-color) !important;
    cursor: pointer;
    display: inline-flex;
    font: inherit;
    height: 1.6rem;
    justify-content: center;
    opacity: 0.62;
    width: 1.6rem;
}
.portfolio-project-table .filter-button:hover {
    background: color-mix(in srgb, var(--st-text-color) 8%, transparent) !important;
    opacity: 1;
}
.portfolio-project-table .filter-button.active {
    background: var(--st-primary-color, #C41039) !important;
    color: white !important;
    opacity: 1;
}
.filter-menu {
    background: var(--st-background-color);
    border: 1px solid color-mix(in srgb, var(--st-text-color) 22%, transparent);
    border-radius: 0.5rem;
    box-shadow: 0 0.5rem 1.5rem color-mix(in srgb, black 20%, transparent);
    min-width: 16rem;
    padding: 0.65rem;
    position: fixed;
    z-index: 10000;
}
.filter-menu input[type="search"] {
    background: var(--st-background-color);
    border: 1px solid color-mix(in srgb, var(--st-text-color) 24%, transparent);
    border-radius: 0.3rem;
    box-sizing: border-box;
    color: var(--st-text-color);
    margin-bottom: 0.5rem;
    padding: 0.45rem 0.55rem;
    width: 100%;
}
.filter-stats {
    background: var(--st-secondary-background-color);
    border-radius: 0.35rem;
    display: grid;
    gap: 0.25rem 0.7rem;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    margin-bottom: 0.5rem;
    padding: 0.5rem;
}
.filter-stat {
    display: flex;
    gap: 0.35rem;
    justify-content: space-between;
}
.filter-stat-label {
    color: color-mix(in srgb, var(--st-text-color) 65%, transparent);
}
.filter-stat-value {
    font-weight: 650;
    overflow: hidden;
    text-overflow: ellipsis;
}
.filter-actions, .sort-actions {
    display: flex;
    gap: 0.35rem;
    margin-bottom: 0.45rem;
}
.filter-actions button, .sort-actions button {
    background: var(--st-secondary-background-color);
    border: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
    border-radius: 0.3rem;
    color: var(--st-text-color);
    cursor: pointer;
    flex: 1;
    padding: 0.35rem 0.45rem;
}
.filter-actions button.primary {
    background: var(--st-primary-color);
    color: white;
}
.value-list {
    border-bottom: 1px solid color-mix(in srgb, var(--st-text-color) 14%, transparent);
    border-top: 1px solid color-mix(in srgb, var(--st-text-color) 14%, transparent);
    max-height: 13rem;
    margin-bottom: 0.5rem;
    overflow-y: auto;
    padding: 0.3rem 0;
}
.value-option {
    align-items: center;
    display: flex;
    gap: 0.45rem;
    padding: 0.22rem 0.1rem;
}
.empty-state {
    color: color-mix(in srgb, var(--st-text-color) 65%, transparent);
    padding: 1.2rem;
    text-align: center;
}
.row-count {
    color: color-mix(in srgb, var(--st-text-color) 65%, transparent);
    font-size: 0.78rem;
    margin-top: 0.35rem;
}
a {
    color: var(--st-link-color);
}
"""

_TABLE_JS = r"""
export default function(component) {
    const {data, parentElement, setStateValue, setTriggerValue} = component;
    const root = parentElement.querySelector('#portfolio-project-table');
    const info = data.page_info;
    const columns = data.columns || [];
    const ROW_HEIGHT = 40, HEADER_HEIGHT = 44, OVERSCAN = 8, PAGE_SIZE = 100;
    let model = root._portfolio;
    if (!model || model.context !== info.context) {
        model?.badgeController?.abort();
        const position = info.preserve_position && model ? {top:model.top, left:model.left} : {top:0,left:0};
        model = root._portfolio = {context: info.context, pages: new Map(), pending: null,
            query: info.query || {}, total: info.total, ...position, menu: null, sequence: 0};
    }
    const dismissFilterMenu = () => {
        model.menu = null;
        clearTimeout(model.searchTimer);
        root.querySelector('.filter-menu')?.remove();
    };
    const outsideFilterMenu = event => {
        const menu = root.querySelector('.filter-menu');
        if (menu && !event.composedPath().includes(menu)) dismissFilterMenu();
    };
    const filterKeydown = event => {if (event.key === 'Escape') dismissFilterMenu();};
    // Composed paths retain the menu identity across Streamlit's shadow root.
    document.addEventListener('pointerdown', outsideFilterMenu, true);
    document.addEventListener('keydown', filterKeydown);
    const removeFilterListeners = () => {
        document.removeEventListener('pointerdown', outsideFilterMenu, true);
        document.removeEventListener('keydown', filterKeydown);
    };
    // A late page/filter response must never replace a newer request's rows.
    if (model.pending && info.request_id !== model.pending.nonce) return removeFilterListeners;
    const pending = model.pending;
    model.pending = null;
    model.query = info.query || {};
    model.total = info.total;
    model.selected = data.selected_id;
    const previousRows = new Map((model.pages.get(info.offset) || []).map(row => [row.project_id, row]));
    for (const row of data.rows || []) {
        if (row.is_overallocated === undefined && previousRows.has(row.project_id)) {
            row.is_overallocated = previousRows.get(row.project_id).is_overallocated;
        }
    }
    model.pages.delete(info.offset);
    model.pages.set(info.offset, data.rows || []);
    while (model.pages.size > 5) model.pages.delete(model.pages.keys().next().value);
    if (model.menu && info.facet && pending?.kind === 'facet' &&
            info.facet.column === model.menu.column && info.facet.search === model.menu.search) {
        model.menu.facet = info.facet;
    }

    const display = (value, column) => {
        if (value === null || value === undefined || value === '') return '—';
        if (column?.format === 'currency') return new Intl.NumberFormat(undefined,
            {style: 'currency', currency: 'EUR', maximumFractionDigits: 2}).format(Number(value));
        return Array.isArray(value) ? value.join(', ') : String(value);
    };
    const request = (kind, extra = {}) => {
        const nonce = String(Date.now()) + '-' + (++model.sequence);
        const payload = {kind, context: model.context, query: model.query,
            offset: Math.floor(Math.max(0, model.top - HEADER_HEIGHT) / ROW_HEIGHT / PAGE_SIZE) * PAGE_SIZE,
            ...extra, nonce};
        model.pending = payload;
        status.textContent = kind === 'facet' ? 'Loading column statistics…' : 'Loading projects…';
        setStateValue('request', payload);
    };
    const changeQuery = () => {
        model.pages.clear();
        model.top = 0;
        scroll.scrollTop = 0;
        dismissFilterMenu();
        request('page', {offset: 0});
        drawRows();
    };
    const closeMenu = () => root.querySelector('.filter-menu')?.remove();
    const closeProjectMenu = () => root.querySelector('.project-context-menu')?.remove();
    const showProjectMenu = (event, row) => {
        event.preventDefault(); event.stopPropagation(); dismissFilterMenu(); closeProjectMenu();
        const menu = document.createElement('div');
        menu.className = 'context-menu project-context-menu'; menu.setAttribute('role', 'menu');
        menu.setAttribute('aria-label', 'Project actions: ' + row.name);
        menu.style.left = Math.max(8, Math.min(event.clientX || 8, window.innerWidth - 280)) + 'px';
        menu.style.top = Math.max(8, Math.min(event.clientY || 44, window.innerHeight - 120)) + 'px';
        const addAction = (label, trigger) => {
            const button = document.createElement('button'); button.type = 'button';
            button.className = 'context-menu-item';
            button.textContent = label; button.setAttribute('role', 'menuitem');
            button.onclick = e => {
                e.stopPropagation(); closeProjectMenu();
                if (trigger === 'row_click') {model.selected = row.project_id; model.redraw?.();}
                setTriggerValue(trigger, row.project_id);
            };
            menu.appendChild(button);
        };
        addAction('Open project details', 'row_click');
        if (row.is_overallocated) addAction('View resource overallocation in Gantt', 'gantt_click');
        root.appendChild(menu); menu.querySelector('button')?.focus();
    };
    root.onclick = closeProjectMenu;
    root.onkeydown = event => {if (event.key === 'Escape') closeProjectMenu();};


    // Retain the actual scrollbar during updates, including an active thumb drag.
    closeMenu(); closeProjectMenu();
    const scroll = root.querySelector('.table-scroll') || document.createElement('div');
    scroll.className = 'table-scroll';
    scroll.setAttribute('aria-label', 'Projects master list; scroll to load projects');
    const table = document.createElement('table');
    table.style.width = (320 + Math.max(0, columns.length - 1) * 190) + 'px';
    const colgroup = document.createElement('colgroup');
    columns.forEach(column => {
        const col = document.createElement('col');
        col.style.width = column.key === 'name' ? '320px' : '190px';
        colgroup.appendChild(col);
    });
    table.appendChild(colgroup);
    const head = document.createElement('thead');
    const header = document.createElement('tr');
    const anchors = new Map();
    columns.forEach(column => {
        const th = document.createElement('th');
        const content = document.createElement('div');
        content.className = 'header-content';
        const label = document.createElement('span');
        label.textContent = column.label;
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'filter-button'; button.textContent = '▼';
        button.setAttribute('aria-label', 'Filter or sort ' + column.label);
        if (model.query.filters?.[column.key] || model.query.sort?.column === column.key) button.classList.add('active');
        button.onclick = () => {
            const rule = model.query.filters?.[column.key] || {mode: 'exclude', values: []};
            model.menu = {column: column.key, search: '', facet: null,
                draft: {mode: rule.mode, values: [...rule.values]}};
            showMenu();
            request('facet', {column: column.key, search: ''});
        };
        anchors.set(column.key, button);
        content.append(label, button); th.appendChild(content); header.appendChild(th);
    });
    head.appendChild(header); table.appendChild(head);
    const body = document.createElement('tbody');
    table.appendChild(body); scroll.replaceChildren(table);
    if (!root.querySelector('.table-scroll')) root.appendChild(scroll);
    const status = root.querySelector('.row-count') || document.createElement('div');
    status.className = 'row-count'; status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    if (!root.querySelector('.row-count')) root.appendChild(status);
    const badgeStatus = root.querySelector('.allocation-status') || document.createElement('div');
    badgeStatus.className = 'allocation-status'; badgeStatus.setAttribute('role', 'status');
    if (!root.querySelector('.allocation-status')) root.appendChild(badgeStatus);

    const loadBadges = () => {
        badgeStatus.replaceChildren();
        if (!info.allocation_endpoint) return;
        if (model.badgeError) {
            const retry = document.createElement('button'); retry.type = 'button';
            retry.textContent = model.badgeError === 409 ? 'Refresh project list' : 'Retry allocation warnings';
            retry.onclick = () => {
                const changed = model.badgeError === 409;
                model.badgeError = null;
                if (changed) request('page');
                else drawRows();
            };
            const message = document.createElement('span'); message.textContent = 'Allocation warnings unavailable. ';
            badgeStatus.append(message, retry);
            return;
        }
        if (model.badgePending) return;
        const first = Math.max(0, Math.floor((model.top - HEADER_HEIGHT) / ROW_HEIGHT));
        const ids = [];
        for (let index = first; index < Math.min(model.total, first + 25); index++) {
            const row = model.pages.get(Math.floor(index / PAGE_SIZE) * PAGE_SIZE)?.[index % PAGE_SIZE];
            if (row && row.is_overallocated === undefined) ids.push(row.project_id);
        }
        if (!ids.length) return;
        const nonce = 'badges-' + Date.now() + '-' + (++model.sequence);
        model.badgePending = nonce;
        model.badgeController = new AbortController();
        const timeout = setTimeout(() => model.badgeController.abort(), 15000);
        fetch(info.allocation_endpoint, {method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'}, signal: model.badgeController.signal,
            body: JSON.stringify({project_ids: ids, revision: info.revision, scope_token: model.context, nonce})})
            .then(async response => {
                if (!response.ok) throw Object.assign(new Error(), {status: response.status});
                const payload = await response.json();
                if (root._portfolio !== model) return;
                if (payload.nonce !== nonce || payload.scope_token !== model.context ||
                    JSON.stringify(payload.project_ids) !== JSON.stringify(ids) ||
                    !Array.isArray(payload.overallocated) || payload.overallocated.some(id => !ids.includes(id))) {
                    throw new Error('Invalid allocation response');
                }
                const overloaded = new Set(payload.overallocated);
                for (const rows of model.pages.values()) {
                    for (const row of rows) if (ids.includes(row.project_id)) row.is_overallocated = overloaded.has(row.project_id);
                }
            })
            .catch(error => {
                if (root._portfolio === model) model.badgeError = error.status || 503;
            })
            .finally(() => {
                clearTimeout(timeout);
                model.badgePending = null;
                if (root._portfolio === model) model.redraw?.();
            });
    };

    const spacer = height => {
        if (!height) return;
        const tr = document.createElement('tr'), td = document.createElement('td');
        tr.className = 'virtual-spacer'; tr.setAttribute('aria-hidden', 'true');
        td.colSpan = columns.length; td.style.height = height + 'px';
        tr.appendChild(td); body.appendChild(tr);
    };
    const drawRows = () => {
        const first = Math.max(0, Math.floor((model.top - HEADER_HEIGHT) / ROW_HEIGHT) - OVERSCAN);
        const last = Math.min(model.total, first + Math.ceil((scroll.clientHeight || 512) / ROW_HEIGHT) + OVERSCAN * 2);
        body.replaceChildren();
        spacer(first * ROW_HEIGHT);
        for (let index = first; index < last; index++) {
            const offset = Math.floor(index / PAGE_SIZE) * PAGE_SIZE;
            const row = model.pages.get(offset)?.[index - offset];
            const tr = document.createElement('tr');
            tr.style.height = ROW_HEIGHT + 'px';
            if (!row) {
                const td = document.createElement('td'); td.colSpan = columns.length;
                td.textContent = 'Loading…'; tr.className = 'loading-row'; tr.appendChild(td);
            } else {
                tr.tabIndex = 0; tr.setAttribute('role', 'button');
                tr.setAttribute('aria-label', 'Open project ' + row.name);
                tr.dataset.projectId = String(row.project_id);
                if (String(row.project_id) === String(model.selected)) tr.classList.add('selected');
                const select = () => {
                    if (String(row.project_id) === String(model.selected)) return;
                    model.selected = row.project_id;
                    root.querySelectorAll('tbody tr.selected').forEach(r => r.classList.remove('selected'));
                    tr.classList.add('selected');
                    setTriggerValue('row_click', row.project_id);
                };
                tr.onclick = select;
                tr.oncontextmenu = event => showProjectMenu(event, row);
                tr.onkeydown = e => {
                    if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) showProjectMenu(e, row);
                    else if (e.key === 'Enter' || e.key === ' ') {e.preventDefault(); select();}
                };
                columns.forEach(column => {
                    const td = document.createElement('td');
                    const text = display(row[column.key], column);
                    td.title = text;
                    if (column.format === 'url' && /^https?:\/\//i.test(String(row[column.key] || ''))) {
                        const link = document.createElement('a');
                        link.href = row[column.key]; link.target = '_blank'; link.rel = 'noopener noreferrer';
                        link.textContent = text; link.onclick = e => e.stopPropagation(); td.appendChild(link);
                    } else if (column.key === 'name' && row.is_overallocated) {
                        const warning = document.createElement('span');
                        warning.className = 'overallocation-indicator';
                        warning.textContent = '⚠';
                        warning.title = 'Resource overallocation';
                        warning.setAttribute('aria-label', warning.title + ': ' + row.name);
                        const name = document.createElement('span'); name.textContent = text;
                        td.append(warning, name);
                    } else td.textContent = text;
                    tr.appendChild(td);
                });
            }
            body.appendChild(tr);
        }
        spacer(Math.max(0, model.total - last) * ROW_HEIGHT);
        loadBadges();
        if (!model.pending) {
            status.textContent = model.total ? model.total.toLocaleString() + ' matching projects · scroll to browse'
                : 'No projects match the filters.';
            // A scrollbar jump may leave an unloaded overscan page above the
            // viewport. Load the rows actually on screen before that hidden gap.
            const visible = Math.max(0, Math.floor((model.top - HEADER_HEIGHT) / ROW_HEIGHT));
            const visibleEnd = Math.min(model.total - 1, visible + Math.ceil((scroll.clientHeight || 512) / ROW_HEIGHT));
            for (let offset = Math.floor(visible / PAGE_SIZE) * PAGE_SIZE; offset <= visibleEnd; offset += PAGE_SIZE) {
                if (!model.pages.has(offset)) {request('page', {offset}); return;}
            }
            // Fill overscan gaps and prefetch only after visible rows are ready.
            const from = Math.floor(first / PAGE_SIZE) * PAGE_SIZE;
            const through = Math.min(model.total - 1, last + 15);
            for (let offset = from; offset <= through; offset += PAGE_SIZE) {
                if (!model.pages.has(offset)) {request('page', {offset}); break;}
            }
        }
    };

    model.redraw = drawRows;

    const showMenu = () => {
        closeMenu();
        const active = model.menu;
        if (!active) return;
        const column = columns.find(c => c.key === active.column);
        if (!column) return;
        const menu = document.createElement('div');
        menu.className = 'filter-menu'; menu.setAttribute('role', 'dialog');
        menu.setAttribute('aria-label', 'Filter ' + column.label);
        const search = document.createElement('input');
        search.type = 'search'; search.placeholder = 'Search all values'; search.value = active.search;
        search.setAttribute('aria-label', 'Search ' + column.label + ' values');
        search.oninput = () => {
            active.search = search.value;
            clearTimeout(model.searchTimer);
            model.searchTimer = setTimeout(() => {
                active.facet = null;
                request('facet', {column: active.column, search: active.search});
            }, 250);
        };
        menu.appendChild(search);
        const facet = active.facet;
        const stats = document.createElement('div'); stats.className = 'filter-stats';
        if (facet) facet.stats.forEach(([name, raw]) => {
            const item = document.createElement('div'); item.className = 'filter-stat';
            const label = document.createElement('span'); label.className = 'filter-stat-label'; label.textContent = name;
            const value = document.createElement('span'); value.className = 'filter-stat-value';
            const isNumber = ['Minimum', 'Average', 'Maximum'].includes(name);
            value.textContent = isNumber ? display(raw, column) : String(raw);
            value.title = value.textContent; item.append(label, value); stats.appendChild(item);
        });
        else stats.textContent = 'Loading full-result statistics…';
        menu.appendChild(stats);
        const sortActions = document.createElement('div'); sortActions.className = 'sort-actions';
        [['asc', 'Sort A → Z'], ['desc', 'Sort Z → A']].forEach(([direction, label]) => {
            const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
            button.onclick = () => {model.query.sort = {column: column.key, direction}; changeQuery();};
            sortActions.appendChild(button);
        });
        menu.appendChild(sortActions);
        const quick = document.createElement('div'); quick.className = 'filter-actions';
        [['Select all', 'exclude'], ['Clear', 'include']].forEach(([label, mode]) => {
            const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
            button.onclick = () => {active.draft = {mode, values: []}; showMenu();};
            quick.appendChild(button);
        });
        menu.appendChild(quick);
        const list = document.createElement('div'); list.className = 'value-list';
        (facet?.values || []).forEach(item => {
            const label = document.createElement('label'); label.className = 'value-option';
            const input = document.createElement('input'); input.type = 'checkbox';
            const contains = active.draft.values.includes(item.value);
            input.checked = active.draft.mode === 'exclude' ? !contains : contains;
            input.onchange = () => {
                const values = new Set(active.draft.values);
                const add = active.draft.mode === 'exclude' ? !input.checked : input.checked;
                if (add) values.add(item.value); else values.delete(item.value);
                active.draft.values = [...values];
            };
            const text = document.createElement('span'); text.textContent = display(item.value, column) + ' (' + item.count + ')';
            label.append(input, text); list.appendChild(label);
        });
        menu.appendChild(list);
        if (facet?.has_more) {
            const hint = document.createElement('div');
            hint.textContent = 'First 200 values. Search to find others. Select all includes every matching value.';
            hint.className = 'row-count'; menu.appendChild(hint);
        }
        const actions = document.createElement('div'); actions.className = 'filter-actions';
        const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancel';
        cancel.onclick = dismissFilterMenu;
        const apply = document.createElement('button'); apply.type = 'button'; apply.className = 'primary'; apply.textContent = 'Apply';
        apply.onclick = () => {
            clearTimeout(model.searchTimer);
            model.query.filters = {...(model.query.filters || {})};
            if (active.draft.mode === 'exclude' && !active.draft.values.length) delete model.query.filters[column.key];
            else model.query.filters[column.key] = active.draft;
            changeQuery();
        };
        actions.append(cancel, apply); menu.appendChild(actions); root.appendChild(menu);
        const rect = anchors.get(column.key).getBoundingClientRect();
        menu.style.left = Math.min(rect.left, Math.max(8, window.innerWidth - 300)) + 'px';
        menu.style.top = Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - 460)) + 'px';
        search.focus();
        search.setSelectionRange(search.value.length, search.value.length);
    };

    let frame;
    scroll.onscroll = () => {
        model.top = scroll.scrollTop; model.left = scroll.scrollLeft;
        if (!frame) frame = requestAnimationFrame(() => {
            frame = null; drawRows();
        });
    };
    drawRows();
    // Keep eight complete rows even when the browser reserves scrollbar space.
    scroll.style.height = (HEADER_HEIGHT + 8 * ROW_HEIGHT +
        Math.max(0, (scroll.offsetHeight || 0) - (scroll.clientHeight || 0))) + 'px';
    scroll.scrollTop = model.top; scroll.scrollLeft = model.left;
    showMenu();
    return () => {
        removeFilterListeners();
        if (frame) cancelAnimationFrame(frame);
    };
}
"""


def _component_value(value: object) -> object:
    """Preserve exact decimals as strings at the JSON component boundary."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _component_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_component_value(item) for item in value]
    return value


def portfolio_project_table(
    rows: list[dict[str, Any]],
    columns: list[dict[str, str]],
    selected_id: Any,
    *,
    key: str,
    page_info: dict[str, Any],
    on_selection_change: Callable[[], None] | None = None,
) -> Any:
    """Render the portfolio table and return the ID from the latest row click."""
    _PORTFOLIO_PROJECT_TABLE = st.components.v2.component(
        "eppm_portfolio_project_table",
        html=_TABLE_HTML,
        css=_TABLE_CSS + CONTEXT_MENU_CSS,
        js=_TABLE_JS,
    )
    result = _PORTFOLIO_PROJECT_TABLE(
        data=_component_value({"rows": rows, "columns": columns, "selected_id": selected_id, "page_info": page_info}),
        key=key,
        width="stretch",
        height="content",
        on_request_change=lambda: None,
        on_row_click_change=on_selection_change or (lambda: None),
        on_gantt_click_change=lambda: None,
    )
    return getattr(result, "row_click", None)
