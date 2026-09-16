"""Shared modal workflows for creating, editing, and deleting projects."""

from collections.abc import Callable
from copy import deepcopy
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import wraps
from typing import Any, TypeVar

import pandas as pd
import streamlit as st

from app.presentation.components.dialog import dialog

from app.application.exceptions import ProjectStorageError, ProjectTypeStorageError, SchemaStorageError
from app.application.ports.business_permissions import PermissionSnapshot
from app.domain.projects.project import PROJECT_STATUSES
from app.domain.projects.project import Project
from app.domain.projects.links import LinkValues
from app.domain.access.models import Permission
from app.presentation.i18n import get_current_locale, t
from app.presentation.components.property_labels import localize_parameters, parameter_groups
from app.presentation.components.dynamic_fields import (
    render_dynamic_field as _render_dynamic_field,
)
from app.presentation.components.project_workspace import ProjectWorkspace
from app.presentation.components.project_type_frames import template_frame, types_frame
from app.presentation.components.project_links import render_links_editor
from app.presentation.components.wbs_editor import render_wbs_editor

STATUS_LIST = list(PROJECT_STATUSES)
_Result = TypeVar("_Result")
_permission_reads: ContextVar[dict[int, PermissionSnapshot] | None] = ContextVar(
    "project_dialog_permission_reads", default=None,
)


def _dialog_errors[**P](function: Callable[P, None]) -> Callable[P, None]:
    @wraps(function)
    def render(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            # Share a current snapshot only within this synchronous dialog render.
            # Independent field-fragment interactions start outside this context.
            with _permission_reads.set({}):
                function(*args, **kwargs)
        except (ValueError, ProjectStorageError, ProjectTypeStorageError, SchemaStorageError) as exc:
            st.error(str(exc))
    return render


@dataclass
class ProjectDialogReferences:
    """Reference display data owned by one open dialog, never shared across users."""

    groups: pd.DataFrame
    options: pd.DataFrame
    managers: dict[int, str]
    type_labels: dict[int, str]
    aliases: dict[str, str]
    templates: dict[int, pd.DataFrame] = field(default_factory=dict)


def _dialog_references(workspace: ProjectWorkspace) -> ProjectDialogReferences:
    catalog = workspace.portfolio.get_catalog()
    types = types_frame(workspace.types.type_choices())
    return ProjectDialogReferences(
        pd.DataFrame(catalog.groups),
        pd.DataFrame(catalog.options, columns=["id", "param_id", "option_value", "display_order"]),
        catalog.managers, dict(zip(types["id"], types["name"])),
        workspace.schema.alias_references(get_current_locale()),
    )


def _dialog_parameters(references: ProjectDialogReferences, type_id: int, workspace: ProjectWorkspace) -> pd.DataFrame:
    if type_id not in references.templates:
        references.templates[type_id] = localize_parameters(
            template_frame(workspace.types.template_reference(type_id)), references.aliases,
        )
    return references.templates[type_id]


def _save_project(save: Callable[..., _Result], **kwargs: Any) -> _Result:
    """Show safe application errors at the UI boundary; kwargs are widget data."""
    try:
        return save(**kwargs)
    except (ValueError, ProjectStorageError) as exc:
        st.error(str(exc))
        st.stop()


def _permissions(workspace: ProjectWorkspace) -> PermissionSnapshot:
    reads = _permission_reads.get()
    if reads is None:
        return workspace.projects.permissions()
    identity = id(workspace.projects)
    if identity not in reads:
        reads[identity] = workspace.projects.permissions()
    return reads[identity]


def _field_permissions(workspace: ProjectWorkspace, project_id: int | None) -> PermissionSnapshot:
    permissions = _save_project(_permissions, workspace=workspace)
    required = Permission.CREATE if project_id is None else Permission.READ
    if not permissions.allows(required, project_id):
        st.error(t("access.create_denied", default="You do not have permission to create projects.")
                 if project_id is None else t("auth.no_access"))
        st.stop()
    return permissions


@st.fragment
def _render_project_basics(
    workspace: ProjectWorkspace, project_id: int, project: Project,
    references: ProjectDialogReferences, *, creating: bool, disabled: bool = False,
) -> tuple[str, str, str, str, int | None]:
    """Edit core fields without rebuilding templates, custom links or the dialog."""
    permissions = _field_permissions(workspace, None if creating else project_id)
    disabled = disabled or (not creating and not permissions.allows(Permission.EDIT, project_id))
    prefix = f"portfolio_{'create' if creating else 'edit'}_{project_id}"
    manager_options = [None, *references.managers]
    manager_labels = {None: "— None —", **references.managers}
    current_manager = int(project.function_id) if project.function_id is not None else None
    id_col, name_col, status_col = st.columns([1, 2, 1])
    id_col.text_input(t("master_data.field_id"), value=str(project_id), disabled=True)
    name = name_col.text_input(t("master_data.field_name"), value=project.name, disabled=disabled, key=prefix + "_name")
    status = status_col.selectbox(t("master_data.field_status"), STATUS_LIST,
        index=STATUS_LIST.index(project.status) if project.status in STATUS_LIST else 0,
        disabled=disabled, key=prefix + "_status")
    planned_col, actual_col, manager_col = st.columns(3)
    planned = planned_col.text_input(t("master_data.field_planned"),
        value=str(project.planned_budget), disabled=disabled, key=prefix + "_planned")
    actual = actual_col.text_input(t("master_data.field_actual"),
        value=str(project.actual_budget), disabled=disabled, key=prefix + "_actual")
    manager = manager_col.selectbox(t("master_data.field_project_manager", default="Project Manager"),
        options=manager_options, index=manager_options.index(current_manager) if current_manager in manager_options else 0,
        format_func=lambda value: manager_labels.get(value, str(value)),
        key=f"portfolio_{'create' if creating else 'edit'}_manager_{project_id}", disabled=disabled)
    return name, status, planned, actual, manager


@st.fragment
def _render_project_properties(
    workspace: ProjectWorkspace, project_id: int | None,
    params: pd.DataFrame, references: ProjectDialogReferences,
    attributes: dict[str, Any], key_prefix: str, *, disabled: bool = False,
    sections: dict[str, Callable[[], None]] | None = None,
) -> dict[str, Any]:
    """Keep dynamic property interactions local while rechecking their current scope."""
    permissions = _field_permissions(workspace, project_id)
    return _render_dynamic_fields(params, references.groups, references.options, attributes, key_prefix,
        disabled=disabled or (project_id is not None and not permissions.allows(Permission.EDIT, project_id)),
        protected_disabled=project_id is not None and not permissions.allows(Permission.PROPERTIES, project_id),
        sections=sections)


def _render_dynamic_fields(
    params: pd.DataFrame,
    groups: pd.DataFrame,
    options: pd.DataFrame,
    attributes: dict[str, Any],
    key_prefix: str,
    disabled: bool = False,
    protected_disabled: bool = False,
    sections: dict[str, Callable[[], None]] | None = None,
) -> dict[str, Any]:
    """Expose every applicable template property, including custom/ungrouped ones.

    Do not use the master-list column whitelist here. Missing values still need
    editable widgets, and required/default rules come from the effective template.
    """
    values: dict[str, Any] = {}
    field_groups = parameter_groups(params, groups)
    links_label = t("portfolio.tab_details_links", default="Useful links")
    field_groups = [(links_label if label.casefold() == "useful links" else label, fields) for label, fields in field_groups]
    for label in sections or {}:
        if label not in [name for name, _ in field_groups]:
            field_groups.append((label, params.iloc[:0]))
    labels = [label for label, _ in field_groups]
    creating = key_prefix.startswith("portfolio_create_")
    if creating:
        labels += [t("project_collaboration.contacts", default="Project Contacts"),
                   t("project_collaboration.log", default="Project log")]
    if not labels:
        return values
    draft = st.session_state.get(f"{key_prefix}_draft", {})
    for _, parameter in params.iterrows():
        param_id = str(parameter["param_id"])
        value = draft.get(param_id, attributes.get(param_id))
        values[param_id] = value.isoformat() if isinstance(value, date) else value
    tabs = st.tabs(labels, key=f"{key_prefix}_tabs", on_change="rerun")
    for tab, (label, fields) in zip(tabs, field_groups):
        if tab.open:
            if st.session_state.get(key_prefix + "_last_tab") != label:
                st.session_state[key_prefix + "_last_tab"] = label
                st.session_state[key_prefix + "_tab_visit"] = st.session_state.get(key_prefix + "_tab_visit", 0) + 1
            with tab:
                for _, parameter in fields.iterrows():
                    param_id = str(parameter["param_id"])
                    values[param_id] = _render_dynamic_field(
                        parameter, options, attributes.get(param_id), key_prefix,
                        disabled=disabled or (protected_disabled and str(parameter.get("param_type")) == "ENUM"),
                    )
                if label in (sections or {}):
                    sections[label]()
    if creating:
        for tab in tabs[-2:]:
            if tab.open:
                with tab:
                    st.info("Create the project to add contacts and log entries.")
    return values


def open_create_project_dialog(
    workspace: ProjectWorkspace,
) -> None:
    """Create a project without leaving the Portfolio Overview."""
    if not workspace.projects.permissions().allows(Permission.CREATE):
        st.error(t("access.create_denied", default="You do not have permission to create projects."))
        return
    draft_key = "portfolio_create_draft_id"
    if draft_key not in st.session_state:
        st.session_state[draft_key] = workspace.projects.generate_project_id()
    project_id = st.session_state[draft_key]
    references = _dialog_references(workspace)
    initial_type = st.session_state.get(f"create_type_{project_id}", next(iter(references.type_labels)))
    _dialog_parameters(references, int(initial_type), workspace)
    _create_project_editor(workspace, project_id, references)


@dialog("Create new project", width="large")
@_dialog_errors
def _create_project_editor(workspace: ProjectWorkspace, project_id: int, references: ProjectDialogReferences) -> None:
    """Retain reference choices while rechecking current creation permission."""
    if not _permissions(workspace).allows(Permission.CREATE):
        st.error(t("access.create_denied", default="You do not have permission to create projects."))
        return
    draft_key = "portfolio_create_draft_id"
    type_labels = references.type_labels
    type_id = st.selectbox(
        t("project_types.label"),
        list(type_labels),
        format_func=type_labels.get,
        key=f"create_type_{project_id}",
    )
    params = _dialog_parameters(references, int(type_id), workspace)
    defaults = {
        p["param_id"]: p["default_value"] for _, p in params.iterrows() if p["has_default"]
    }
    with st.container():
        name, status, planned, actual, manager = _render_project_basics(
            workspace, project_id, Project(planned_budget=Decimal(150000)), references, creating=True,
        )
        st.write(f"#### {t('project_types.template')}")
        sections, draft = _assignment_sections(workspace, None, [], f"portfolio_create_{project_id}")
        dynamic_values = _render_project_properties(
            workspace, None, params, references, defaults, f"portfolio_create_{project_id}", sections=sections,
        )
        if st.button("Create project", icon=":material/add:", width="stretch"):
            clean_name = name.strip()
            if not clean_name:
                st.error(t("master_data.err_required_fields"))
            else:
                created_id = _save_project(
                    workspace.projects.create_project,
                    name=clean_name,
                    status=status,
                    planned_budget=planned,
                    actual_budget=actual,
                    dynamic_attributes=dynamic_values,
                    function_id=manager,
                    project_type_id=int(type_id),
                    custom_links=draft["links"], wbs_allocations=draft["wbs"],
                )
                st.session_state.pop(draft_key, None)
                st.session_state.pop(f"portfolio_create_{project_id}_assignments", None)
                st.session_state["selected_portfolio_project_id"] = created_id
                st.toast("Project created.", icon="✅")
                st.rerun()


def _dismiss_project_dialog() -> None:
    """Clear a pending confirmation when the user dismisses the project modal."""
    st.session_state.pop("project_delete_confirmation", None)
    st.session_state.pop("project_fields_editing", None)
    if (project_id := st.session_state.pop("project_edit_draft_id", None)) is not None:
        st.session_state.pop(f"portfolio_edit_{project_id}_draft", None)
        st.session_state.pop(f"portfolio_edit_{project_id}_assignments", None)


def _assignment_sections(workspace: ProjectWorkspace, project_id: int | None,
                         links: list[LinkValues], prefix: str, *, disabled: bool = False
                         ) -> tuple[dict[str, Callable[[], None]], dict[str, Any]]:
    """Retain optional sections across tab switches and save them with the project."""
    key = prefix + "_assignments"
    if key not in st.session_state:
        st.session_state[key] = {"links": links, "wbs": workspace.projects.get_wbs_allocations(project_id) if project_id else [],
                                 "options": workspace.projects.get_wbs_options(project_id)}
    draft = st.session_state[key]

    def initial(section: str) -> tuple[list, str]:
        # A data_editor applies deltas to its input frame. Keep that frame stable
        # while mounted; when returning to a tab, mount the last accepted draft.
        visit = st.session_state.get(prefix + "_tab_visit", 0)
        if draft.get(section + "_visit") != visit:
            draft[section + "_initial"] = deepcopy(draft[section])
            draft[section + "_visit"] = visit
        return draft[section + "_initial"], f"{prefix}_{section}_{visit}"

    def links_section() -> None:
        values, widget_key = initial("links")
        draft["links"] = render_links_editor(values, widget_key, disabled=disabled)

    def wbs_section() -> None:
        values, widget_key = initial("wbs")
        draft["wbs"] = render_wbs_editor(values, draft["options"], widget_key, disabled=disabled)

    return {t("portfolio.tab_details_links", default="Useful links"): links_section,
            t("wbs.title", default="WBS"): wbs_section}, draft


def open_edit_project_dialog(
    project_id: int,
    workspace: ProjectWorkspace,
    read_only: bool = False,
    allow_edit: bool = True,
) -> None:
    """Edit or delete one project without navigating to another page."""
    project = workspace.projects.get_project_by_id(project_id)
    if project is None:
        st.error("The selected project no longer exists.")
        return

    st.session_state["project_edit_draft_id"] = project_id
    references = _dialog_references(workspace)
    initial_type = st.session_state.get(f"edit_type_{project_id}", project.project_type_id)
    _dialog_parameters(references, int(initial_type), workspace)
    links = workspace.projects.get_links(project_id)
    _edit_project_editor(project_id, workspace, project, references, links, read_only, allow_edit)


@dialog("Project details", width="large", on_dismiss=_dismiss_project_dialog)
@_dialog_errors
def _edit_project_editor(
    project_id: int, workspace: ProjectWorkspace, project: Project,
    references: ProjectDialogReferences, links: list[LinkValues], read_only: bool,
    allow_edit: bool = True,
) -> None:
    """Retain the editable draft and references; authorize every dialog interaction."""

    permissions = _permissions(workspace)
    if not permissions.allows(Permission.READ, project_id):
        st.error(t("auth.no_access", default="Your account has no assigned application access. Contact an access administrator."))
        return
    can_edit = allow_edit and permissions.allows(Permission.EDIT, project_id)
    can_delete = allow_edit and permissions.allows(Permission.DELETE, project_id)
    can_change_scope = allow_edit and permissions.allows(Permission.PROPERTIES, project_id)
    if can_edit and read_only and st.session_state.get("project_fields_editing") != project_id:
        with st.container(horizontal=True, horizontal_alignment="right"):
            if st.button(t("project_collaboration.edit_project", default="Edit project"),
                         key=f"enable_project_edit_{project_id}", type="primary"):
                st.session_state["project_fields_editing"] = project_id
    disabled = not can_edit or (read_only and st.session_state.get("project_fields_editing") != project_id)

    confirmation_key = "project_delete_confirmation"
    if can_delete and st.session_state.get(confirmation_key) == project_id:
        st.subheader("Confirm project deletion")
        st.warning(f"Delete {project.name}? Its tasks, dependencies, contacts, and log entries will also be removed.")
        with st.container(horizontal=True):
            if st.button("Confirm delete project", type="primary", key=f"confirm_delete_project_{project_id}"):
                _save_project(workspace.projects.delete_project, project_id=project_id)
                st.session_state.pop(confirmation_key, None)
                if str(st.session_state.get("selected_portfolio_project_id")) == str(project_id):
                    st.session_state.pop("selected_portfolio_project_id", None)
                st.toast("Project deleted.")
                st.rerun()
            st.button("Cancel", key=f"cancel_delete_project_{project_id}",
                on_click=st.session_state.pop, args=(confirmation_key, None))
        return

    type_labels = references.type_labels
    type_id = st.selectbox(
        t("project_types.label"),
        list(type_labels),
        index=list(type_labels).index(project.project_type_id),
        format_func=type_labels.get,
        key=f"edit_type_{project_id}",
        disabled=disabled or not can_change_scope,
    )
    params = _dialog_parameters(references, int(type_id), workspace)
    with st.container():
        name, status, planned, actual, manager = _render_project_basics(
            workspace, project_id, project, references, creating=False, disabled=disabled,
        )
        st.write(f"#### {t('project_types.template')}")
        sections, draft = _assignment_sections(workspace, project_id, links, f"portfolio_edit_{project_id}", disabled=disabled)
        dynamic_values = _render_project_properties(
            workspace, project_id, params, references, dict(project.dynamic_attributes or {}),
            f"portfolio_edit_{project_id}", disabled=disabled, sections=sections,
        )
        if st.button(t("master_data.btn_update"), key=f"save_project_{project_id}", width="stretch", disabled=disabled):
            clean_name = name.strip()
            if not clean_name:
                st.error(t("master_data.err_required_fields"))
            else:
                updated = _save_project(
                    workspace.projects.update_project,
                    project_id=project_id,
                    name=clean_name,
                    status=status,
                    planned_budget=planned,
                    actual_budget=actual,
                    dynamic_attributes=dynamic_values,
                    function_id=manager,
                    project_type_id=int(type_id),
                    custom_links=draft["links"], wbs_allocations=draft["wbs"],
                )
                if not updated:
                    st.error("The selected project no longer exists.")
                    st.stop()
                st.toast("Project details updated.", icon="✅")
                _dismiss_project_dialog()
                st.rerun()

    if can_delete:
        st.divider()
        st.button("Delete project", icon=":material/delete:", key=f"portfolio_delete_project_{project_id}",
            disabled=disabled,
            on_click=st.session_state.__setitem__, args=(confirmation_key, project_id))
