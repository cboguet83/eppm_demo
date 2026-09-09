"""Shared modal workflows for creating, editing, and deleting projects."""

from collections.abc import Callable
from typing import Any, TypeVar

import pandas as pd
import streamlit as st

from app.application.exceptions import ProjectStorageError
from app.domain.projects.project import PROJECT_STATUSES
from app.presentation.i18n import get_current_locale, t
from app.presentation.components.property_labels import localize_parameters, parameter_groups
from app.presentation.components.dynamic_fields import (
    render_dynamic_field as _render_dynamic_field,
)
from app.presentation.components.project_workspace import ProjectWorkspace
from app.presentation.components.project_type_frames import template_frame, types_frame

STATUS_LIST = list(PROJECT_STATUSES)
_Result = TypeVar("_Result")


def _save_project(save: Callable[..., _Result], **kwargs: Any) -> _Result:
    """Show safe application errors at the UI boundary; kwargs are widget data."""
    try:
        return save(**kwargs)
    except (ValueError, ProjectStorageError) as exc:
        st.error(str(exc))
        st.stop()


def _manager_options(
    workspace: ProjectWorkspace,
) -> tuple[list[int | None], dict[int | None, str]]:
    """Use injected editor reference data with the existing vacant-position label."""
    names = workspace.portfolio.get_catalog().managers
    return [None, *names], {None: "— None —", **names}


def _render_dynamic_fields(
    params: pd.DataFrame,
    groups: pd.DataFrame,
    options: pd.DataFrame,
    attributes: dict[str, Any],
    key_prefix: str,
) -> dict[str, Any]:
    """Expose every applicable template property, including custom/ungrouped ones.

    Do not use the master-list column whitelist here. Missing values still need
    editable widgets, and required/default rules come from the effective template.
    """
    values: dict[str, Any] = {}
    field_groups = parameter_groups(params, groups)
    labels = [label for label, _ in field_groups]
    creating = key_prefix.startswith("portfolio_create_")
    if creating:
        labels += [t("project_collaboration.contacts", default="Project Contacts"),
                   t("project_collaboration.log", default="Project log")]
    if not labels:
        return values
    tabs = st.tabs(labels)
    for tab, (_, fields) in zip(tabs, field_groups):
        with tab:
            for _, parameter in fields.iterrows():
                param_id = str(parameter["param_id"])
                values[param_id] = _render_dynamic_field(
                    parameter, options, attributes.get(param_id), key_prefix,
                )
    if creating:
        for tab in tabs[-2:]:
            with tab:
                st.info("Create the project to add contacts and log entries.")
    return values


@st.dialog("Create new project", width="large")
def open_create_project_dialog(
    workspace: ProjectWorkspace,
) -> None:
    """Create a project without leaving the Portfolio Overview."""
    draft_key = "portfolio_create_draft_id"
    if draft_key not in st.session_state:
        st.session_state[draft_key] = workspace.projects.generate_project_id()
    project_id = st.session_state[draft_key]
    catalog = workspace.portfolio.get_catalog()
    groups = pd.DataFrame(catalog.groups)
    options = pd.DataFrame(
        catalog.options, columns=["id", "param_id", "option_value", "display_order"]
    )
    manager_options = [None, *catalog.managers]
    manager_labels = {None: "— None —", **catalog.managers}

    type_options = types_frame(workspace.types.get_all_types())
    type_labels = dict(zip(type_options["id"], type_options["name"]))
    type_id = st.selectbox(
        t("project_types.label"),
        list(type_labels),
        format_func=type_labels.get,
        key=f"create_type_{project_id}",
    )
    params = localize_parameters(
        template_frame(workspace.types.get_template(int(type_id))),
        workspace.schema.get_alias_translations(get_current_locale()),
    )
    defaults = {
        p["param_id"]: p["default_value"] for _, p in params.iterrows() if p["has_default"]
    }
    with st.container():
        id_col, name_col, status_col = st.columns([1, 2, 1])
        id_col.text_input(t("master_data.field_id"), value=str(project_id), disabled=True)
        name = name_col.text_input(t("master_data.field_name"))
        status = status_col.selectbox(t("master_data.field_status"), options=STATUS_LIST)

        planned_col, actual_col, manager_col = st.columns(3)
        planned = planned_col.number_input(
            t("master_data.field_planned"), min_value=0.0, value=150000.0, step=5000.0
        )
        actual = actual_col.number_input(
            t("master_data.field_actual"), min_value=0.0, value=0.0, step=5000.0
        )
        manager = manager_col.selectbox(
            t("master_data.field_project_manager", default="Project Manager"),
            options=manager_options,
            format_func=lambda value: manager_labels.get(value, str(value)),
            key=f"portfolio_create_manager_{project_id}",
        )

        st.write(f"#### {t('project_types.template')}")
        dynamic_values = _render_dynamic_fields(
            params,
            groups,
            options,
            defaults,
            f"portfolio_create_{project_id}",
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
                )
                st.session_state.pop(draft_key, None)
                st.session_state["selected_portfolio_project_id"] = created_id
                st.toast("Project created.", icon="✅")
                st.rerun()


def _dismiss_project_dialog() -> None:
    """Clear a pending confirmation when the user dismisses the project modal."""
    st.session_state.pop("project_delete_confirmation", None)


@st.dialog("Edit project details", width="large", on_dismiss=_dismiss_project_dialog)
def open_edit_project_dialog(
    project_id: int,
    workspace: ProjectWorkspace,
) -> None:
    """Edit or delete one project without navigating to another page."""
    project = workspace.projects.get_project_by_id(project_id)
    if project is None:
        st.error("The selected project no longer exists.")
        return

    confirmation_key = "project_delete_confirmation"
    if st.session_state.get(confirmation_key) == project_id:
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
                on_click=_dismiss_project_dialog)
        return

    catalog = workspace.portfolio.get_catalog()
    groups = pd.DataFrame(catalog.groups)
    options = pd.DataFrame(
        catalog.options, columns=["id", "param_id", "option_value", "display_order"]
    )
    manager_options = [None, *catalog.managers]
    manager_labels = {None: "— None —", **catalog.managers}
    current_manager = int(project.function_id) if project.function_id is not None else None
    manager_index = (
        manager_options.index(current_manager) if current_manager in manager_options else 0
    )

    type_options = types_frame(workspace.types.get_all_types())
    type_labels = dict(zip(type_options["id"], type_options["name"]))
    type_id = st.selectbox(
        t("project_types.label"),
        list(type_labels),
        index=list(type_labels).index(project.project_type_id),
        format_func=type_labels.get,
        key=f"edit_type_{project_id}",
    )
    params = localize_parameters(
        template_frame(workspace.types.get_template(int(type_id))),
        workspace.schema.get_alias_translations(get_current_locale()),
    )
    with st.container():
        id_col, name_col, status_col = st.columns([1, 2, 1])
        id_col.text_input(t("master_data.field_id"), value=str(project_id), disabled=True)
        name = name_col.text_input(t("master_data.field_name"), value=project.name)
        status_index = STATUS_LIST.index(project.status) if project.status in STATUS_LIST else 0
        status = status_col.selectbox(
            t("master_data.field_status"), options=STATUS_LIST, index=status_index
        )

        planned_col, actual_col, manager_col = st.columns(3)
        planned = planned_col.number_input(
            t("master_data.field_planned"),
            min_value=0.0,
            value=float(project.planned_budget),
            step=5000.0,
        )
        actual = actual_col.number_input(
            t("master_data.field_actual"),
            min_value=0.0,
            value=float(project.actual_budget),
            step=5000.0,
        )
        manager = manager_col.selectbox(
            t("master_data.field_project_manager", default="Project Manager"),
            options=manager_options,
            index=manager_index,
            format_func=lambda value: manager_labels.get(value, str(value)),
            key=f"portfolio_edit_manager_{project_id}",
        )

        st.write(f"#### {t('project_types.template')}")
        dynamic_values = _render_dynamic_fields(
            params,
            groups,
            options,
            dict(project.dynamic_attributes or {}),
            f"portfolio_edit_{project_id}",
        )
        if st.button(t("master_data.btn_update"), width="stretch"):
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
                )
                if not updated:
                    st.error("The selected project no longer exists.")
                    st.stop()
                st.toast("Project details updated.", icon="✅")
                st.rerun()

    st.divider()
    st.button("Delete project", icon=":material/delete:", key=f"portfolio_delete_project_{project_id}",
        on_click=st.session_state.__setitem__, args=(confirmation_key, project_id))
