"""Portfolio project drafts and authorized saves for a local browser modal."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from sys import float_info
from typing import Any
from uuid import uuid4

import streamlit as st

from app.application.exceptions import ProjectStorageError, ProjectTypeStorageError, SchemaStorageError
from app.domain.access.models import Permission
from app.domain.projects.project import Project, PROJECT_STATUSES
from app.domain.projects.wbs import normalize_allocations
from app.presentation.components.project_dialogs import (
    ProjectDialogReferences, _dialog_references, _dialog_parameters,
)
from app.presentation.components.project_form import project_form
from app.presentation.components.project_workspace import ProjectWorkspace
from app.presentation.components.property_labels import parameter_groups
from app.presentation.i18n import t

_STATE = "portfolio_project_modal_state"
_ERROR = "portfolio_project_modal_error"
_NOTICE = "portfolio_project_modal_notice"


@dataclass
class ProjectDraft:
    """Retain identity and references on the server; JSON values remain untrusted."""

    project_id: int | None
    project: Project
    references: ProjectDialogReferences
    token: str = field(default_factory=lambda: uuid4().hex)
    # Any is confined to heterogeneous property values at this component boundary.
    form: dict[str, Any] = field(default_factory=dict)
    edited: dict[str, Any] = field(default_factory=dict)


def _project_form(workspace: ProjectWorkspace, draft: ProjectDraft, type_id: int) -> dict[str, Any]:
    permissions = workspace.projects.permissions()
    required = Permission.CREATE if draft.project_id is None else Permission.EDIT
    if not permissions.allows(required, draft.project_id):
        raise ValueError("You do not have permission to edit this project." if draft.project_id else
                         "You do not have permission to create projects.")
    if type_id not in draft.references.type_labels:
        raise ValueError("Select a valid project template.")
    can_scope = draft.project_id is None or permissions.allows(Permission.PROPERTIES, draft.project_id)
    project, references = draft.project, draft.references
    values = {
        "display_id": str(draft.project_id or ""),
        "name": project.name, "status": project.status, "planned_budget": str(project.planned_budget),
        "actual_budget": str(project.actual_budget), "function_id": str(project.function_id or ""),
        "project_type_id": str(type_id),
    }
    values.update({key: value for key, value in draft.form.get("values", {}).items() if not key.startswith("p:")})
    values["project_type_id"] = str(type_id)
    fields = []

    def add(key, label, kind, *, options=None, disabled=False, tab=None):
        fields.append(dict(key=key, label=label, kind=kind, options=options or [], disabled=disabled, tab=tab))

    add("display_id", t("master_data.field_id"), "text", disabled=True)
    add("project_type_id", t("project_types.label"), "select", disabled=not can_scope,
        options=[(str(key), label) for key, label in references.type_labels.items()])
    add("name", t("master_data.field_name"), "text")
    add("status", t("master_data.field_status"), "select", options=[(value, value) for value in PROJECT_STATUSES])
    add("planned_budget", t("master_data.field_planned"), "money")
    add("actual_budget", t("master_data.field_actual"), "money")
    add("function_id", t("master_data.field_project_manager", default="Project Manager"), "select",
        options=[("", "— None —"), *[(str(key), label) for key, label in references.managers.items()]])
    params = _dialog_parameters(references, type_id, workspace)
    groups = parameter_groups(params, references.groups)
    links_tab = t("portfolio.tab_details_links", default="Useful links")
    groups = [(links_tab if label.casefold() == "useful links" else label, fields) for label, fields in groups]
    tabs = [label for label, _ in groups]
    if links_tab not in tabs:
        tabs.append(links_tab)
    wbs_tab = t("wbs.title", default="WBS")
    if wbs_tab not in tabs:
        tabs.append(wbs_tab)
    for label, parameters in groups:
        for _, parameter in parameters.iterrows():
            param_id = str(parameter["param_id"])
            key, kind = "p:" + param_id, str(parameter["param_type"]).upper()
            value = (parameter["default_value"] if parameter["has_default"] else None) if draft.project_id is None else (
                project.dynamic_attributes or {}).get(param_id)
            value = draft.edited.get(key, value)
            values[key] = value.isoformat() if isinstance(value, date) else value
            choices = references.options[references.options.param_id == param_id].option_value.tolist()
            if kind in {"MULTI_ENUM", "TAGS"}:
                values[key] = value if isinstance(value, list) else [value] if value else []
                choices = list(dict.fromkeys([*choices, *values[key]]))
            else:
                choices = ["", *choices]
            alias = parameter.get("alias")
            title = alias.strip() if isinstance(alias, str) and alias.strip() else str(parameter["param_name"])
            if parameter.get("mandatory"):
                title += " *"
            add(key, title, {"NUMBER": "number", "DATE": "date", "ENUM": "select",
                            "MULTI_ENUM": "multi", "TAGS": "tags"}.get(kind, "text"),
                options=[(str(value), str(value)) for value in choices],
                disabled=kind == "ENUM" and not can_scope, tab=label)
    messages = {}
    if draft.project_id is None:
        for label in [t("project_collaboration.contacts", default="Project Contacts"), t("project_collaboration.log", default="Project log")]:
            tabs.append(label)
            messages[label] = "Create the project to add contacts and log entries."
    return dict(
        token=draft.token, title="Create new project" if draft.project_id is None else f"Edit project #{draft.project_id}",
        fields=fields, tabs=tabs, messages=messages, values=values,
        links=draft.form.get("links", []), error="", can_save=True,
        links_tab=links_tab, wbs_tab=wbs_tab,
        wbs=draft.form.get("wbs", []), wbs_options=draft.form.get("wbs_options", []),
        wbs_labels={key: t("wbs." + key) for key in ("code", "allocation", "available", "add", "remove", "select", "empty")},
        can_delete=draft.project_id is not None and permissions.allows(Permission.DELETE, draft.project_id),
        submit="Create project" if draft.project_id is None else t("master_data.btn_update"),
        cancel=t("settings.btn_cancel", default="Cancel"),
        links_label=t("project_collaboration.custom_links", default="Custom links"),
        alias_label=t("project_collaboration.link_alias", default="Display alias"),
    )


def begin_project_dialog(workspace: ProjectWorkspace, project_id: int | None = None) -> None:
    """Prepare one complete form in the opening button's callback."""
    st.session_state.pop(_STATE, None)
    st.session_state.pop(_ERROR, None)
    st.session_state.pop(_NOTICE, None)
    try:
        required = Permission.CREATE if project_id is None else Permission.EDIT
        if not workspace.projects.permissions().allows(required, project_id):
            raise ValueError("You do not have permission to edit this project." if project_id else
                             "You do not have permission to create projects.")
        project = Project(planned_budget=Decimal(150000)) if project_id is None else workspace.projects.get_project_by_id(project_id)
        if project is None:
            raise ValueError("The selected project no longer exists.")
        references = _dialog_references(workspace)
        draft = ProjectDraft(project_id, project, references)
        draft.form["values"] = {"display_id": str(workspace.projects.generate_project_id() if project_id is None else project_id)}
        if project_id is not None:
            draft.form["links"] = workspace.projects.get_links(project_id)
            draft.form["wbs"] = workspace.projects.get_wbs_allocations(project_id)
        draft.form["wbs_options"] = workspace.projects.get_wbs_options(project_id)
        type_id = next(iter(references.type_labels)) if project_id is None else project.project_type_id
        draft.form = _project_form(workspace, draft, int(type_id))
        st.session_state[_STATE] = draft
    except (ValueError, ProjectStorageError, ProjectTypeStorageError, SchemaStorageError) as exc:
        st.session_state[_ERROR] = str(exc)
    st.rerun("portfolio_project_modal")


def _accept_values(draft: ProjectDraft, event: dict[str, Any]) -> dict[str, Any]:
    values, links, dirty = event.get("values"), event.get("links"), event.get("dirty")
    if not isinstance(values, dict) or set(values) != set(draft.form["values"]):
        raise ValueError("Invalid project form. Please reopen the project and try again.")
    kinds = {field["key"]: field["kind"] for field in draft.form["fields"]}
    for key, value in values.items():
        kind = kinds[key]
        if kind in {"multi", "tags"}:
            valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
        elif kind == "number":
            valid = value is None or type(value) in {int, float} and -float_info.max <= value <= float_info.max
        else:
            valid = isinstance(value, str)
        if not valid:
            raise ValueError("Invalid project field value.")
    if not isinstance(dirty, list) or any(not isinstance(key, str) or key not in values for key in dirty):
        raise ValueError("Invalid project field changes.")
    if not isinstance(links, list) or any(
        not isinstance(link, dict) or set(link) != {"alias", "url"}
        or any(not isinstance(value, str) for value in link.values()) for link in links
    ):
        raise ValueError("Each custom link needs a display alias and URL.")
    draft.form["values"], draft.form["links"] = values, links
    draft.form["wbs"] = normalize_allocations(event.get("wbs", draft.form.get("wbs", [])))
    draft.edited.update({key: values[key] for key in dirty if key.startswith("p:")})
    return values


def _save(workspace: ProjectWorkspace, draft: ProjectDraft, values: dict[str, Any]) -> int:
    name = values["name"].strip()
    if not name:
        raise ValueError(t("master_data.err_required_fields"))
    if any(not isinstance(values[key], str) or not values[key].strip() for key in ("planned_budget", "actual_budget")):
        raise ValueError("Enter planned and actual budget amounts.")
    arguments = dict(
        name=name, status=values["status"], planned_budget=values["planned_budget"], actual_budget=values["actual_budget"],
        function_id=int(values["function_id"]) if values["function_id"] else None,
        project_type_id=int(values["project_type_id"]),
        dynamic_attributes={key[2:]: value for key, value in values.items() if key.startswith("p:")},
        custom_links=[link for link in draft.form["links"] if link["alias"] or link["url"]],
        wbs_allocations=draft.form["wbs"],
    )
    if draft.project_id is None:
        return workspace.projects.create_project(**arguments)
    if not workspace.projects.update_project(project_id=draft.project_id, **arguments):
        raise ValueError("The selected project no longer exists.")
    return draft.project_id


def _project_action(workspace: ProjectWorkspace) -> None:
    draft = st.session_state.get(_STATE)
    event = st.session_state.get("portfolio_project_form", {}).get("action")
    if not draft or not isinstance(event, dict) or event.get("token") != draft.token:
        return
    kind = event.get("kind")
    if kind == "cancel":
        st.session_state.pop(_STATE, None)
        return
    if kind not in {"save", "type", "delete"}:
        return
    try:
        values = _accept_values(draft, event)
        if kind == "type":
            draft.form = _project_form(workspace, draft, int(values["project_type_id"]))
            return
        if kind == "delete":
            if draft.project_id is None:
                raise ValueError("Create the project before deleting it.")
            if not workspace.projects.delete_project(draft.project_id):
                raise ValueError("The selected project no longer exists.")
            selected = None
            st.session_state[_NOTICE] = "Project deleted."
        else:
            selected = _save(workspace, draft, values)
            st.session_state[_NOTICE] = "Project created." if draft.project_id is None else "Project details updated."
        st.session_state.pop(_STATE, None)
        st.session_state["selected_portfolio_project_id"] = selected
        st.session_state["portfolio_selection_override"] = selected
        st.session_state["portfolio_preserve_grid_position"] = True
        st.rerun(["portfolio_grid", "portfolio_selection", "portfolio_project_modal"])
    except (ValueError, ProjectStorageError, ProjectTypeStorageError, SchemaStorageError) as exc:
        draft.form["error"] = str(exc)


@st.fragment(key="portfolio_project_modal")
def render_project_modal(workspace: ProjectWorkspace) -> None:
    """Retain the modal independently from the grid, project summary and sidebar."""
    if error := st.session_state.pop(_ERROR, None):
        st.error(error)
    draft = st.session_state.get(_STATE)
    project_form(draft.form if draft else None, on_action=lambda: _project_action(workspace))
    if notice := st.session_state.pop(_NOTICE, None):
        # Deliver acknowledgement with the refreshed UI, after the save callback.
        st.toast(notice)
