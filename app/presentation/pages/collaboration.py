"""Lazy, form-based project contacts, event logs and their settings catalogs."""

from functools import wraps
from collections.abc import Callable
from typing import Literal, TypedDict

import pandas as pd
import streamlit as st

from app.presentation.i18n import get_current_locale, t
from app.domain.projects.collaboration import CatalogKind, EVENT_SCOPES, EVENT_STATUSES
from app.application.services.collaboration import CollaborationService
from app.application.ports.collaboration import ProjectEvent
from app.presentation.components.modal_form import ModalField, ModalForm, modal_form
from app.application.exceptions import CollaborationConflictError, CollaborationStorageError


def _label(key: str, default: str) -> str:
    return t("project_collaboration." + key, default=default)


def _change(action: Callable[[], object], error_key: str) -> None:
    """Apply writes in a widget callback, before the one automatic rerender."""
    try:
        action()
        st.session_state.pop(error_key, None)
    except (ValueError, CollaborationStorageError) as error:
        st.session_state[error_key] = (
            _label(
                "integrity_error",
                "Cannot save: this entry is duplicated, missing, or still in use.",
            )
            if isinstance(error, CollaborationConflictError)
            else str(error)
        )


def _show_error(key: str) -> None:
    if error := st.session_state.pop(key, None):
        st.error(error)


def collaboration_errors[**P](function: Callable[P, None]) -> Callable[P, None]:
    """Keep safe validation and storage errors within the rendered section."""

    @wraps(function)
    def render(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            function(*args, **kwargs)
        except (ValueError, CollaborationStorageError) as error:
            st.error(str(error))

    return render


@st.fragment
@collaboration_errors
def render_project_catalog(service: CollaborationService, kind: CatalogKind) -> None:
    """Maintain the role/type catalog without loading unrelated settings tabs."""
    st.subheader(
        _label("roles", "Project roles") if kind == "role" else _label("types", "Event types")
    )
    rows = service.list_catalog(kind)
    if rows:
        st.dataframe(
            pd.DataFrame([{_label("name", "Name"): row["name"]} for row in rows]),
            hide_index=True,
            width="stretch",
            height="auto",
        )
    choices = {row["id"]: row["name"] for row in rows}
    prefix = "project_catalog_" + kind
    item_id = st.selectbox(
        _label("catalog_entry", "Catalog entry"),
        [None, *choices],
        format_func=lambda value: choices.get(value, _label("new_entry", "New entry")),
        key=prefix + "_selection",
    )
    with st.form(f"{prefix}_{item_id}"):
        name_key = f"{prefix}_{item_id}_name"
        st.text_input(_label("name", "Name"), value=choices.get(item_id, ""), key=name_key)

        def save_entry() -> None:
            saved_id = service.save_catalog(kind, st.session_state[name_key], item_id)
            st.session_state[prefix + "_selection"] = saved_id

        st.form_submit_button(
            _label("save", "Save"),
            type="primary",
            on_click=_change,
            args=(save_entry, prefix + "_error"),
        )
    if item_id is not None:
        confirmed = st.checkbox(
            _label("confirm_delete", "Confirm deletion"), key=f"{prefix}_confirm_{item_id}"
        )

        def delete_entry() -> None:
            service.delete_catalog(kind, item_id)
            st.session_state[prefix + "_selection"] = None

        st.button(
            _label("delete", "Delete"),
            disabled=not confirmed,
            key=prefix + "_delete",
            on_click=_change,
            args=(delete_entry, prefix + "_error"),
        )
    _show_error(prefix + "_error")


@st.fragment
@collaboration_errors
def render_project_contacts(project_id: int, service: CollaborationService) -> None:
    """Show current contact details with row actions and a separate add dialog."""
    from app.presentation.components.action_table import action_table

    contacts = service.list_contacts(project_id, get_current_locale())
    can_edit = service.can_edit(project_id)
    if can_edit and st.button(_label("add_contact", "Add contact"), icon=":material/person_add:", key=f"add_contact_{project_id}"):
        _contact_dialog(project_id, service)
    if not contacts:
        _render_modal(project_id, "contacts", service)
        st.info(_label("no_contacts", "No project contacts assigned."))
        return
    rows = [dict(row, accessible_name=f"{row['role']} — {row['person']}") for row in contacts]
    event = action_table(rows, [
        ("role", _label("role", "Role")), ("person", _label("person", "Person")),
        ("function_name", _label("function", "Function")),
        ("mobile", _label("mobile", "Mobile")), ("landline", _label("landline", "Landline")),
    ], {"reassign": _label("reassign", "Reassign"), "remove": _label("remove_contact", "Remove contact")} if can_edit else {},
        key=f"project_contacts_table_{project_id}")
    if event:
        if event["action"] == "reassign":
            _contact_dialog(project_id, service, event["id"])
        elif event["action"] == "remove":
            _remove_contact_dialog(project_id, service, event["id"])
    _render_modal(project_id, "contacts", service)


def _modal_key(project_id: int, surface: str) -> str:
    return f"project_{surface}_{project_id}_modal"


class CollaborationModal(TypedDict):
    """Server-owned operation and row identity, separate from submitted values."""

    operation: Literal["contact", "remove", "event"]
    id: int | None
    form: ModalForm


def _select_field(
    key: str, label: str, choices: dict[int, str] | dict[str, str], *, disabled: bool = False, compact: bool = False,
) -> ModalField:
    return ModalField(key=key, label=label, kind="select",
                      options=[(str(value), text) for value, text in choices.items()], disabled=disabled, compact=compact)


@collaboration_errors
def _contact_dialog(project_id: int, service: CollaborationService, contact_id: int | None = None) -> None:
    """Prepare authorized contact fields before displaying a complete modal."""
    st.session_state.pop(_modal_key(project_id, "contacts") + "_state", None)
    if not service.can_edit(project_id):
        st.info(t("access.read_only", default="You have read-only access to this project."))
        return
    locale = get_current_locale()
    roles = {row["id"]: row["label"] for row in service.list_catalog("role", locale)}
    functions = {row["function_id"]: f"{row['person']} \u2014 {row['function_name']} (#{row['function_id']})"
                 for row in service.function_choices()}
    contacts = {row["id"]: row for row in service.list_contacts(project_id, locale)}
    if contact_id is not None and contact_id not in contacts:
        st.error("The contact assignment no longer exists.")
        return
    if not roles or not functions:
        st.info(_label("configure_contacts", "Create project roles and functions in Settings before assigning contacts."))
        return
    current = contacts.get(contact_id, {})
    form = ModalForm(title="Project contact", submit=_label("save_contact", "Save contact"),
        cancel=_label("cancel", "Cancel"), error="", fields=[
            _select_field("role_id", _label("role", "Role"), roles, disabled=contact_id is not None),
            _select_field("function_id", _label("function", "Function"), functions),
        ], values={"role_id": str(current.get("role_id", next(iter(roles)))),
                   "function_id": str(current.get("function_id", next(iter(functions))))})
    st.session_state[_modal_key(project_id, "contacts") + "_state"] = {
        "operation": "contact", "id": contact_id, "form": form,
    }


@collaboration_errors
def _remove_contact_dialog(project_id: int, service: CollaborationService, contact_id: int) -> None:
    """Prepare confirmation without exposing unrelated employee details."""
    st.session_state.pop(_modal_key(project_id, "contacts") + "_state", None)
    if not service.can_edit(project_id):
        st.info(t("access.read_only", default="You have read-only access to this project."))
        return
    contact = next((row for row in service.list_contacts(project_id, get_current_locale()) if row["id"] == contact_id), None)
    if contact is None:
        st.info("The contact assignment no longer exists.")
        return
    st.session_state[_modal_key(project_id, "contacts") + "_state"] = {
        "operation": "remove", "id": contact_id,
        "form": ModalForm(title="Confirm contact removal", submit="Confirm removal", cancel=_label("cancel", "Cancel"),
            fields=[], values={}, error="", message=f"Remove {contact['person']} from the role {contact['role']}?"),
    }


@collaboration_errors
def _event_dialog(project_id: int, service: CollaborationService, current: ProjectEvent | None = None) -> None:
    """Prepare authorized log fields before displaying the modal in one step."""
    st.session_state.pop(_modal_key(project_id, "log") + "_state", None)
    if not service.can_edit(project_id):
        st.info(t("access.read_only", default="You have read-only access to this project."))
        return
    types = {row["id"]: row["label"] for row in service.list_catalog("event_type", get_current_locale())}
    if not types:
        st.info(_label("configure_events", "Create event types in Settings before logging an event."))
        return
    fields = [ModalField(key=key, label=_label(key, label), kind=kind) for key, label, kind in (
        ("title", "Title", "text"), ("description", "Description", "textarea"))]
    fields.extend([
        _select_field("event_type_id", _label("event_type", "Event type"), types, compact=True),
        _select_field("status", _label("state", "State"),
                      {value: _label("state_" + value, value.title()) for value in EVENT_STATUSES}, compact=True),
        _select_field("scope", _label("scope", "Scope"),
                      {value: _label("scope_" + value, value.title()) for value in EVENT_SCOPES}, compact=True),
        ModalField(key="deadline", label=_label("deadline", "Deadline"), kind="date"),
        ModalField(key="comment", label=_label("comment", "Comment"), kind="textarea"),
    ])
    values = {"title": "", "description": "", "comment": "", "deadline": "", "status": "new",
              "scope": "internal", "event_type_id": str(next(iter(types)))}
    if current:
        values.update({key: str(current[key]) if current[key] is not None else "" for key in values})
    st.session_state[_modal_key(project_id, "log") + "_state"] = {
        "operation": "event", "id": current["id"] if current else None,
        "form": ModalForm(title="Project log entry", submit=_label("save_event", "Save event"),
                          cancel=_label("cancel", "Cancel"), fields=fields, values=values, error="", wide=True),
    }


def _selected_identifier(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or len(value) > 18 or int(value) <= 0:
        raise ValueError("Select a valid entry from the available choices.")
    return int(value)


def _save_modal(project_id: int, service: CollaborationService, state: CollaborationModal, values: dict[str, str]) -> None:
    """Use the retained row identity and authoritative services for each mutation."""
    identity = state["id"]
    if state["operation"] == "remove":
        service.delete_contact(project_id, identity)
    elif state["operation"] == "contact":
        function_id = _selected_identifier(values["function_id"])
        if identity is None:
            service.save_contact(project_id, _selected_identifier(values["role_id"]), function_id)
        else:
            service.reassign_contact(project_id, identity, function_id)
    else:
        saved_id = service.save_event(project_id, event_id=identity,
            event_type_id=_selected_identifier(values["event_type_id"]), deadline=values["deadline"] or None,
            **{key: values[key] for key in ("title", "description", "comment", "status", "scope")})
        if identity is None:
            st.session_state[f"project_log_{project_id}_offset"] = 0
            st.session_state[f"project_log_{project_id}_selection"] = saved_id


def _modal_action(project_id: int, surface: str, service: CollaborationService) -> None:
    """Commit before the section rerender; retain entered values on safe failures."""
    key = _modal_key(project_id, surface)
    state = st.session_state.get(key + "_state")
    event = st.session_state.get(key, {}).get("action")
    if not state or not isinstance(event, dict):
        return
    if event.get("kind") == "cancel":
        st.session_state.pop(key + "_state", None)
        return
    if event.get("kind") != "save":
        return
    values = event.get("values")
    expected = state["form"]["values"]
    if not isinstance(values, dict) or set(values) != set(expected) or any(not isinstance(value, str) for value in values.values()):
        state["form"]["error"] = "Invalid form submission. Please check the entered values."
        return
    state["form"]["values"] = values
    error_key = key + "_error"
    _change(lambda: _save_modal(project_id, service, state, values), error_key)
    if error := st.session_state.pop(error_key, None):
        state["form"]["error"] = error
    else:
        st.session_state.pop(key + "_state", None)


def _render_modal(project_id: int, surface: str, service: CollaborationService) -> None:
    key = _modal_key(project_id, surface)
    state = st.session_state.get(key + "_state")
    modal_form(state["form"] if state else None, key=key,
               on_action=lambda: _modal_action(project_id, surface, service))


@st.fragment
def _render_project_event_dialog(project_id: int, service: CollaborationService) -> None:
    """Handle standalone event submission without rerendering the planning chart."""
    _render_modal(project_id, "log", service)


def open_project_event_dialog(project_id: int, service: CollaborationService) -> None:
    """Open the shared authorized event form without loading the project log list.

    Args:
        project_id: Project receiving the new event.
        service: Actor-scoped collaboration service, which reauthorizes saves.
    """
    _event_dialog(project_id, service)
    _render_project_event_dialog(project_id, service)


@st.fragment
@collaboration_errors
def render_project_log(project_id: int, service: CollaborationService) -> None:
    """Show a bounded multiline log table with modal creation and row editing."""
    locale = get_current_locale()
    types = {row["id"]: row["label"] for row in service.list_catalog("event_type", locale)}
    prefix = f"project_log_{project_id}"
    offset = st.session_state.get(prefix + "_offset", 0)
    page = service.list_events(project_id, locale, offset=offset, limit=51)
    rows = page[:50]
    can_edit = service.can_edit(project_id)
    if can_edit and st.button(_label("add_event", "Add event"), icon=":material/add:", key=prefix + "_add", disabled=not types):
        _event_dialog(project_id, service)
    if rows:
        from app.presentation.components.action_table import action_table

        display_rows = [dict(row, status=_label("state_" + row["status"], row["status"].title()),
                             scope=_label("scope_" + row["scope"], row["scope"].title())) for row in rows]
        event = action_table(display_rows, [
            ("title", _label("title", "Title")), ("description", _label("description", "Description")),
            ("event_type", _label("event_type", "Event type")), ("status", _label("state", "State")),
            ("deadline", _label("deadline", "Deadline")), ("scope", _label("scope", "Scope")),
            ("comment", _label("comment", "Comment")),
        ], {"edit": _label("edit_event", "Edit entry")} if can_edit else {}, key=prefix + "_table", context_menu=True)
        if event:
            _event_dialog(project_id, service, next(row for row in rows if row["id"] == event["id"]))
    else:
        st.info(_label("no_events", "No events logged for this project."))
    _render_modal(project_id, "log", service)
    if offset or len(page) > 50:

        def move_page(delta: int) -> None:
            st.session_state[prefix + "_offset"] = max(0, offset + delta)
            st.session_state[prefix + "_selection"] = None

        with st.container(horizontal=True):
            st.button(
                _label("previous", "Previous"),
                disabled=offset == 0,
                key=prefix + "_previous",
                on_click=move_page,
                args=(-50,),
            )
            st.button(
                _label("next", "Next"),
                disabled=len(page) <= 50,
                key=prefix + "_next",
                on_click=move_page,
                args=(50,),
            )
    if not types:
        st.info(
            _label("configure_events", "Create event types in Settings before logging an event.")
        )
        return


@st.fragment
@collaboration_errors
def render_project_links(project_id: int, service: CollaborationService) -> None:
    """Inspect custom links; editing is available in the project dialog."""
    from app.presentation.components.project_links import render_link_rows
    links = service.list_links(project_id)
    st.divider()
    render_link_rows(links)
