"""Accessible row actions for allocation and contact display tables."""

from typing import TypedDict

import streamlit as st


class TableAction(TypedDict):
    """Validated row identity and requested action from the display component."""

    id: int
    action: str


_TABLE_JS = r"""
export default function({data, parentElement, setTriggerValue}) {
    const root = parentElement.querySelector('.action-table');
    root.replaceChildren();
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
        for (const [key] of data.columns) {
            const cell = document.createElement('td'); cell.textContent = String(row[key] ?? '—');
            tr.appendChild(cell);
        }
        const controls = document.createElement('td'); controls.className = 'actions';
        for (const [action, label] of Object.entries(data.actions)) {
            const button = document.createElement('button'); button.type = 'button';
            button.textContent = label;
            button.setAttribute('aria-label', `${label}: ${row.accessible_name ?? row.id}`);
            button.onclick = () => setTriggerValue('action', {id: row.id, action});
            controls.appendChild(button);
        }
        tr.appendChild(controls); body.appendChild(tr);
    }
    table.appendChild(body); root.appendChild(table);
}
"""

_TABLE_CSS = """
    .action-table {overflow: auto; max-height: 440px;}
    table {width: 100%; border-collapse: collapse; font: inherit; font-size: 14px;}
    th, td {padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--st-border-color);}
    th {position: sticky; top: 0; background: var(--st-background-color);}
    .actions {white-space: nowrap;}
    button {font: inherit; color: var(--st-text-color); background: var(--st-background-color);
        border: 1px solid var(--st-border-color); border-radius: 5px; padding: 4px 8px;
        margin-right: 5px; cursor: pointer;}
    button:hover {border-color: var(--st-primary-color); color: var(--st-primary-color);}
    button:focus-visible {outline: 2px solid var(--st-primary-color); outline-offset: 2px;}
    """


def action_table(
    rows: list[dict[str, object]],
    columns: list[tuple[str, str]],
    actions: dict[str, str],
    *,
    key: str,
    action_label: str = "Actions",
) -> TableAction | None:
    """Render JSON display rows and accept only visible IDs and allowed actions."""
    # Registration belongs to the current runtime; AppTest creates a new registry.
    table = st.components.v2.component(
        "eppm_action_table", html='<div class="action-table"></div>', css=_TABLE_CSS, js=_TABLE_JS,
    )
    result = table(
        data={"rows": rows, "columns": columns, "actions": actions, "action_label": action_label},
        key=key, width="stretch", height="content", on_action_change=lambda: None,
    )
    event = getattr(result, "action", None)
    if not isinstance(event, dict) or event.get("action") not in actions:
        return None
    identity = event.get("id")
    if type(identity) is not int or identity not in {row["id"] for row in rows}:
        return None
    return TableAction(id=identity, action=event["action"])
