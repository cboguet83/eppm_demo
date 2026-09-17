"""Accessible row actions for allocation and contact display tables."""

from typing import TypedDict

import streamlit as st
from app.presentation.components.context_menu import CONTEXT_MENU_CSS


class TableAction(TypedDict):
    """Validated row identity and requested action from the display component."""

    id: int
    action: str


_TABLE_JS = r"""
export default function({data, parentElement, setTriggerValue}) {
    const root = parentElement.querySelector('.action-table');
    root.replaceChildren();
    let menu = null;
    let tooltip = null;
    const closeTooltip = () => {tooltip?.remove(); tooltip = null;};
    const showTooltip = (cell, message) => {
        closeTooltip(); tooltip = document.createElement('span');
        tooltip.className = 'allocation-overlay'; tooltip.setAttribute('role', 'tooltip');
        tooltip.textContent = message; root.appendChild(tooltip);
        const rect = cell.getBoundingClientRect();
        tooltip.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - 420)) + 'px';
        tooltip.style.top = Math.max(8, Math.min(rect.bottom, window.innerHeight - tooltip.offsetHeight - 8)) + 'px';
    };
    const actionsFor = row => Object.entries(data.actions).filter(([action]) => !row.allowed_actions || row.allowed_actions.includes(action));
    const closeMenu = () => {if (menu) {menu.remove(); menu = null;}};
    const showMenu = (event, row) => {
        event.preventDefault(); event.stopPropagation(); closeMenu();
        menu = document.createElement('div'); menu.className = 'context-menu';
        menu.setAttribute('role', 'menu');
        for (const [action, label] of actionsFor(row)) {
            const button = document.createElement('button'); button.type = 'button';
            button.className = 'context-menu-item'; button.textContent = label;
            button.setAttribute('role', 'menuitem');
            button.onclick = () => {closeMenu(); setTriggerValue('action', {id: row.id, action});};
            menu.appendChild(button);
        }
        root.appendChild(menu);
        menu.style.left = Math.max(10, Math.min(event.clientX, window.innerWidth - menu.offsetWidth - 10)) + 'px';
        menu.style.top = Math.max(10, Math.min(event.clientY, window.innerHeight - menu.offsetHeight - 10)) + 'px';
        menu.querySelector('button')?.focus();
    };
    const table = document.createElement('table');
    const head = document.createElement('thead');
    const header = document.createElement('tr');
    for (const [, label] of data.columns) {
        const cell = document.createElement('th'); cell.textContent = label;
        cell.scope = 'col'; header.appendChild(cell);
    }
    const actionHeader = document.createElement('th'); actionHeader.textContent = data.action_label;
    actionHeader.scope = 'col'; header.appendChild(actionHeader);
    head.appendChild(header); table.appendChild(head);
    const body = document.createElement('tbody');
    for (const row of data.rows) {
        const tr = document.createElement('tr');
        if (data.context_menu) {
            tr.oncontextmenu = event => showMenu(event, row);
            tr.tabIndex = 0;
            tr.onkeydown = event => {
                if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
                    const rect = tr.getBoundingClientRect();
                    showMenu({preventDefault: () => event.preventDefault(), stopPropagation: () => event.stopPropagation(),
                        clientX: rect.left + 10, clientY: rect.bottom}, row);
                }
            };
        }
        for (const [key] of data.columns) {
            const cell = document.createElement('td'); cell.textContent = String(row[key] ?? '—');
            if (row.tooltips?.[key]) {
                cell.tabIndex = 0; cell.className = 'allocation-warning';
                cell.style.color = '#c41039'; cell.setAttribute('aria-label', row.tooltips[key]);
                cell.onmouseenter = cell.onfocus = () => showTooltip(cell, row.tooltips[key]);
                cell.onmouseleave = cell.onblur = closeTooltip;
                cell.onkeydown = event => {if (event.key === 'Escape') closeTooltip();};
            }
            tr.appendChild(cell);
        }
        const controls = document.createElement('td'); controls.className = 'actions';
        for (const [action, label] of actionsFor(row)) {
            const button = document.createElement('button'); button.type = 'button';
            button.textContent = label;
            button.setAttribute('aria-label', `${label}: ${row.accessible_name ?? row.id}`);
            button.onclick = () => setTriggerValue('action', {id: row.id, action});
            controls.appendChild(button);
        }
        tr.appendChild(controls); body.appendChild(tr);
    }
    table.appendChild(body); root.appendChild(table);
    if (data.context_menu) {
        const outside = event => {if (menu && !event.composedPath().includes(menu)) closeMenu();};
        const keydown = event => {if (event.key === 'Escape') closeMenu();};
        document.addEventListener('pointerdown', outside);
        document.addEventListener('keydown', keydown);
        document.addEventListener('scroll', closeMenu, true);
        return () => {
            document.removeEventListener('pointerdown', outside);
            document.removeEventListener('keydown', keydown);
            document.removeEventListener('scroll', closeMenu, true);
            closeMenu();
        };
    }
}
"""

_TABLE_CSS = """
    .action-table {overflow-x: hidden; overflow-y: auto; max-height: 440px;}
    table {width: 100%; table-layout: fixed; border-collapse: collapse; font: inherit; font-size: 14px;}
    th, td {white-space: pre-wrap; overflow-wrap: anywhere; vertical-align: top;}
    th, td {padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--st-border-color);}
    th {position: sticky; top: 0; background: var(--st-background-color);}
    .actions {white-space: normal;}
    .allocation-overlay {position:fixed;z-index:10000;background:var(--st-background-color,#fff);
        color:var(--st-text-color,#262730);border:1px solid #9ca3af;border-radius:4px;padding:10px;
        max-width:400px;box-shadow:0 2px 8px #0003;pointer-events:none;}
    button {font: inherit; color: white; background: #C41039;
        border: 1px solid var(--st-border-color); border-radius: 5px; padding: 4px 8px;
        margin-right: 5px; cursor: pointer;}
    button:hover {border-color: #C41039; filter: brightness(.92);}
    button:focus-visible {outline: 2px solid var(--st-primary-color); outline-offset: 2px;}
    """


def action_table(
    rows: list[dict[str, object]],
    columns: list[tuple[str, str]],
    actions: dict[str, str],
    *,
    key: str,
    action_label: str = "Actions",
    context_menu: bool = False,
) -> TableAction | None:
    """Render JSON display rows and accept only visible IDs and allowed actions."""
    # Registration belongs to the current runtime; AppTest creates a new registry.
    table = st.components.v2.component(
        "eppm_action_table", html='<div class="action-table"></div>', css=_TABLE_CSS + CONTEXT_MENU_CSS, js=_TABLE_JS,
    )
    result = table(
        data={"rows": rows, "columns": columns, "actions": actions, "action_label": action_label,
              "context_menu": context_menu},
        key=key, width="stretch", height="content", on_action_change=lambda: None,
    )
    event = getattr(result, "action", None)
    if not isinstance(event, dict):
        return None
    action = event.get("action")
    if not isinstance(action, str) or action not in actions:
        return None
    identity = event.get("id")
    if type(identity) is not int or identity not in {row["id"] for row in rows}:
        return None
    row = next(row for row in rows if row['id'] == identity)
    if 'allowed_actions' in row and action not in row['allowed_actions']:
        return None
    return TableAction(id=identity, action=action)
