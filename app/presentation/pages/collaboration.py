"""Lazy, form-based project contacts, event logs and their settings catalogs."""

from functools import wraps
from collections.abc import Callable
from datetime import date

import pandas as pd
import streamlit as st

from app.presentation.i18n import get_current_locale, t
from app.domain.projects.collaboration import CatalogKind, EVENT_SCOPES, EVENT_STATUSES
from app.application.services.collaboration import CollaborationService
from app.application.ports.collaboration import ProjectEvent
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
    if st.button(_label("add_contact", "Add contact"), icon=":material/person_add:", key=f"add_contact_{project_id}"):
        _contact_dialog(project_id, service)
    if not contacts:
        st.info(_label("no_contacts", "No project contacts assigned."))
        return
    rows = [dict(row, accessible_name=f"{row['role']} — {row['person']}") for row in contacts]
    event = action_table(rows, [
        ("role", _label("role", "Role")), ("person", _label("person", "Person")),
        ("function_name", _label("function", "Function")),
        ("mobile", _label("mobile", "Mobile")), ("landline", _label("landline", "Landline")),
    ], {"reassign": _label("reassign", "Reassign"), "remove": _label("remove_contact", "Remove contact")},
        key=f"project_contacts_table_{project_id}")
    if event:
        if event["action"] == "reassign":
            _contact_dialog(project_id, service, event["id"])
        elif event["action"] == "remove":
            _remove_contact_dialog(project_id, service, event["id"])


@st.dialog("Project contact")
@collaboration_errors
def _contact_dialog(project_id: int, service: CollaborationService, contact_id: int | None = None) -> None:
    """Create a role assignment or reassign its function while retaining the role."""
    locale = get_current_locale()
    roles = {row["id"]: row["label"] for row in service.list_catalog("role", locale)}
    functions = {row["function_id"]: row for row in service.function_choices()}
    contacts = {row["id"]: row for row in service.list_contacts(project_id, locale)}
    if contact_id is not None and contact_id not in contacts:
        st.error("The contact assignment no longer exists.")
        return
    if not roles or not functions:
        st.info(_label("configure_contacts", "Create project roles and functions in Settings before assigning contacts."))
        return
    current = contacts.get(contact_id, {})
    prefix = f"project_contact_{project_id}_{contact_id}"
    with st.form(prefix):
        role_id = st.selectbox(_label("role", "Role"), list(roles), format_func=roles.get,
            index=list(roles).index(current.get("role_id", next(iter(roles)))),
            disabled=contact_id is not None, key=prefix + "_role")
        function_id = st.selectbox(_label("function", "Function"), list(functions),
            format_func=lambda value: f"{functions[value]['person']} — {functions[value]['function_name']} (#{value})",
            index=list(functions).index(current.get("function_id", next(iter(functions)))), key=prefix + "_function")
        if st.form_submit_button(_label("save_contact", "Save contact"), type="primary"):
            if contact_id is None:
                service.save_contact(project_id, role_id, function_id)
            else:
                service.reassign_contact(project_id, contact_id, function_id)
            st.rerun()


@st.dialog("Confirm contact removal")
@collaboration_errors
def _remove_contact_dialog(project_id: int, service: CollaborationService, contact_id: int) -> None:
    """Confirm removal of an assignment without deleting its employee or function."""
    contact = next((row for row in service.list_contacts(project_id, get_current_locale()) if row["id"] == contact_id), None)
    if contact is None:
        st.info("The contact assignment no longer exists.")
        return
    st.write(f"Remove {contact['person']} from the role {contact['role']}?")
    with st.container(horizontal=True):
        if st.button("Confirm removal", type="primary", key=f"confirm_contact_remove_{contact_id}"):
            service.delete_contact(project_id, contact_id)
            st.rerun()
        if st.button("Cancel", key=f"cancel_contact_remove_{contact_id}"):
            st.rerun()


def _event_form(
    service: CollaborationService,
    project_id: int,
    current: ProjectEvent | None,
    types: dict[int, str],
) -> None:
    event_id = current["id"] if current else None
    prefix = f"project_log_{project_id}_{event_id if event_id is not None else 'new'}"
    with st.form(prefix):
        st.text_input(
            _label("title", "Title"),
            value=current["title"] if current else "",
            key=prefix + "_title",
        )
        st.text_area(
            _label("description", "Description"),
            value=current["description"] if current else "",
            key=prefix + "_description",
        )
        cols = st.columns(3)
        cols[0].selectbox(
            _label("event_type", "Event type"),
            list(types),
            format_func=types.get,
            key=prefix + "_event_type_id",
            index=list(types).index(current["event_type_id"] if current else next(iter(types))),
        )
        cols[1].selectbox(
            _label("state", "State"),
            EVENT_STATUSES,
            key=prefix + "_status",
            format_func=lambda value: _label("state_" + value, value.title()),
            index=EVENT_STATUSES.index(current["status"] if current else "new"),
        )
        cols[2].selectbox(
            _label("scope", "Scope"),
            EVENT_SCOPES,
            key=prefix + "_scope",
            format_func=lambda value: _label("scope_" + value, value.title()),
            index=EVENT_SCOPES.index(current["scope"] if current else "internal"),
        )
        st.date_input(
            _label("deadline", "Deadline"),
            key=prefix + "_deadline",
            value=(
                date.fromisoformat(current["deadline"])
                if current and current["deadline"]
                else None
            ),
        )
        st.text_area(
            _label("comment", "Comment"),
            value=current["comment"] if current else "",
            key=prefix + "_comment",
        )

        def save_event() -> None:
            values = {
                field: st.session_state[prefix + "_" + field]
                for field in (
                    "title",
                    "description",
                    "scope",
                    "comment",
                    "event_type_id",
                    "status",
                )
            }
            deadline = st.session_state[prefix + "_deadline"]
            saved_id = service.save_event(
                project_id,
                **values,
                deadline=deadline.isoformat() if deadline else None,
                event_id=event_id,
            )
            if not current:
                st.session_state[f"project_log_{project_id}_offset"] = 0
                st.session_state[f"project_log_{project_id}_selection"] = saved_id

        submitted = st.form_submit_button(
            _label("save_event", "Save event"),
            type="primary",
            on_click=_change,
            args=(save_event, prefix + "_error"),
        )
    if submitted and not st.session_state.get(prefix + "_error"):
        st.rerun()
    _show_error(prefix + "_error")


@st.dialog("Project log entry", width="large")
@collaboration_errors
def _event_dialog(
    project_id: int, service: CollaborationService, current: ProjectEvent | None = None,
) -> None:
    """Create or edit a project log entry in a modal."""
    types = {row["id"]: row["label"] for row in service.list_catalog("event_type", get_current_locale())}
    if not types:
        st.info(_label("configure_events", "Create event types in Settings before logging an event."))
        return
    _event_form(service, project_id, current, types)


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
    if st.button(_label("add_event", "Add event"), icon=":material/add:", key=prefix + "_add", disabled=not types):
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
        ], {"edit": _label("edit_event", "Edit entry")}, key=prefix + "_table", context_menu=True)
        if event:
            _event_dialog(project_id, service, next(row for row in rows if row["id"] == event["id"]))
    else:
        st.info(_label("no_events", "No events logged for this project."))
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
