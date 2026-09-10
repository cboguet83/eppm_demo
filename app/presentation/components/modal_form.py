"""A browser-native modal form that closes after an acknowledged local save."""

from collections.abc import Callable
from typing import Literal, NotRequired, TypedDict

import streamlit as st


class ModalField(TypedDict):
    """An allowlisted input description, with labels rendered as plain text."""

    key: str
    label: str
    kind: Literal["text", "textarea", "select", "date"]
    options: NotRequired[list[tuple[str, str]]]
    disabled: NotRequired[bool]
    compact: NotRequired[bool]


class ModalForm(TypedDict):
    """Prepared display data and retained values for one open modal."""

    title: str
    submit: str
    cancel: str
    fields: list[ModalField]
    values: dict[str, str]
    error: str
    message: NotRequired[str]
    wide: NotRequired[bool]


_JS = r"""
export default function({data, parentElement, setTriggerValue}) {
    const dialog = parentElement.querySelector('dialog');
    if (!data) { if (dialog.open) dialog.close(); return; }
    dialog.replaceChildren();
    dialog.className = data.wide ? 'wide' : '';
    const title = document.createElement('h2'); title.id = 'modal-title';
    title.textContent = data.title; dialog.appendChild(title);
    const form = document.createElement('form'); form.noValidate = true;
    const controls = new Map();
    if (data.message) {
        const message = document.createElement('p'); message.textContent = data.message;
        form.appendChild(message);
    }
    const grid = document.createElement('div'); grid.className = 'fields';
    for (const field of data.fields) {
        const label = document.createElement('label');
        if (field.compact) label.className = 'compact';
        const caption = document.createElement('span'); caption.textContent = field.label;
        label.appendChild(caption);
        const input = document.createElement(field.kind === 'select' ? 'select' : field.kind === 'textarea' ? 'textarea' : 'input');
        if (field.kind === 'text' || field.kind === 'date') input.type = field.kind;
        if (field.kind === 'select') {
            for (const [value, text] of field.options) {
                const option = document.createElement('option'); option.value = value;
                option.textContent = text; input.appendChild(option);
            }
        }
        input.name = field.key; input.setAttribute('aria-label', field.label);
        input.value = data.values[field.key] ?? '';
        input.disabled = Boolean(field.disabled);
        label.appendChild(input); grid.appendChild(label); controls.set(field.key, input);
    }
    form.appendChild(grid);
    if (data.error) {
        const error = document.createElement('p'); error.className = 'error';
        error.setAttribute('role', 'alert'); error.textContent = data.error; form.appendChild(error);
    }
    const footer = document.createElement('div'); footer.className = 'buttons';
    const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = data.cancel;
    const submit = document.createElement('button'); submit.type = 'submit'; submit.textContent = data.submit;
    footer.append(cancel, submit); form.appendChild(footer); dialog.appendChild(form);
    let pending = false;
    const dismiss = () => {
        if (pending) return;
        dialog.close(); setTriggerValue('action', {kind: 'cancel'});
    };
    cancel.onclick = dismiss;
    dialog.oncancel = event => {event.preventDefault(); dismiss();};
    dialog.onclick = event => {
        const rect = dialog.getBoundingClientRect();
        if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dismiss();
    };
    form.onsubmit = event => {
        event.preventDefault(); if (pending) return;
        pending = true; submit.disabled = true; cancel.disabled = true;
        form.setAttribute('aria-busy', 'true');
        setTriggerValue('action', {kind: 'save', values: Object.fromEntries([...controls].map(([key, input]) => [key, input.value]))});
    };
    // Populate the complete form before displaying the modal, including on retry.
    if (!dialog.open) dialog.showModal();
}
"""

_CSS = """
dialog {box-sizing: border-box; width: min(500px, calc(100vw - 32px)); max-height: 90vh;
    padding: 24px; border: 1px solid var(--st-border-color); border-radius: 12px;
    color: var(--st-text-color); background: var(--st-background-color); font: inherit;
    box-shadow: 0 12px 48px #0003; overflow-y: auto;}
dialog.wide {width: min(1100px, calc(100vw - 32px));}
dialog::backdrop {background: #0006;}
h2 {font-size: 1.35rem; margin: 0 0 20px;}
.fields {display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px;}
label {display: flex; flex-direction: column; gap: 6px; grid-column: 1 / -1;}
label.compact {grid-column: span 1;}
input, select, textarea {box-sizing: border-box; width: 100%; font: inherit; color: inherit;
    background: var(--st-secondary-background-color); border: 1px solid var(--st-border-color);
    border-radius: 6px; padding: 9px 12px;}
textarea {min-height: 95px; resize: vertical;}
.buttons {display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;}
button {font: inherit; cursor: pointer; color: white; background: #C41039;
    border: 1px solid #C41039; border-radius: 6px; padding: 8px 14px;}
:disabled {opacity: .55; cursor: default;}
:focus-visible {outline: 2px solid #C41039; outline-offset: 2px;}
.error {background: #fde8ec; color: #970329; padding: 12px; border-radius: 6px;}
@media(max-width: 640px) {label.compact {grid-column: 1 / -1;}}
"""


def modal_form(data: ModalForm | None, *, key: str, on_action: Callable[[], None]) -> None:
    """Keep a local modal mounted and dispatch save/cancel events to its owner."""
    component = st.components.v2.component(
        "eppm_modal_form", html='<dialog aria-labelledby="modal-title"></dialog>', css=_CSS, js=_JS,
    )
    component(data=data, key=key, on_action_change=on_action, width="stretch", height=0)
