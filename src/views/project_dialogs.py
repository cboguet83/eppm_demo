"""Shared modal workflows for creating, editing, and deleting projects."""

import datetime
import sqlite3
from typing import Any, Optional

import pandas as pd
import streamlit as st

from src.i18n import t
from app.presentation.components.dynamic_fields import render_dynamic_field as _render_dynamic_field
from src.models.constants import (
    PARAM_TYPE_DATE,
    PARAM_TYPE_ENUM,
    PARAM_TYPE_HYPERLINK,
    PARAM_TYPE_MULTI_ENUM,
    PARAM_TYPE_NUMBER,
    PARAM_TYPE_TAGS,
    PARAM_TYPE_TEXT,
    PARAM_TYPE_URL,
    STATUS_LIST,
)
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.project_type_repo import ProjectTypeRepository
from src.repositories.schema_repo import SchemaRepository
from src.services.organization_service import OrganizationService
from src.services.schema_service import SchemaService


def _save_project(save, **kwargs):
    try:
        return save(**kwargs)
    except (ValueError, sqlite3.IntegrityError) as exc:
        st.error(str(exc))
        st.stop()


def _dynamic_project_value(attributes: dict[str, Any], parameter: pd.Series) -> Any:
    """Find an existing dynamic value by parameter ID, name, or alias."""
    param_id = str(parameter["param_id"])
    param_name = str(parameter.get("param_name", ""))
    alias = (
        str(parameter.get("alias", "")).strip()
        if pd.notna(parameter.get("alias"))
        else ""
    )
    value = attributes.get(param_id)
    if value is None and param_name:
        value = attributes.get(param_name)
    if value is None and alias:
        value = attributes.get(alias)
    return value


def _manager_options(
    project_repo: ProjectRepository,
) -> tuple[list[Optional[int]], dict[Optional[int], str]]:
    """Return position IDs labeled by occupant name, with vacant-position fallback."""
    org_repo = OrganizationRepository(project_repo.db_path)
    functions = org_repo.get_all_functions()
    employees = org_repo.get_all_employees()
    names = OrganizationService.get_function_occupant_names(functions, employees)
    options: list[Optional[int]] = [None]
    if not functions.empty:
        options.extend(int(value) for value in functions["function_id"].tolist())
    return options, {None: "— None —", **names}


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
    known_group_ids = set(groups["id"].tolist()) if not groups.empty else set()

    if not groups.empty and not params.empty:
        for _, group in groups.iterrows():
            group_params = params[params["group_id"] == group["id"]]
            if group_params.empty:
                continue
            with st.expander(f":material/folder: {group['group_name']}", expanded=True):
                for _, parameter in group_params.iterrows():
                    param_id = str(parameter["param_id"])
                    values[param_id] = _render_dynamic_field(
                        parameter,
                        options,
                        _dynamic_project_value(attributes, parameter),
                        key_prefix,
                    )

    if not params.empty:
        ungrouped = params[
            params["group_id"].isna() | ~params["group_id"].isin(known_group_ids)
        ]
        if not ungrouped.empty:
            with st.expander(
                f":material/push_pin: {t('schema.param_group_none')}",
                expanded=True,
            ):
                for _, parameter in ungrouped.iterrows():
                    param_id = str(parameter["param_id"])
                    values[param_id] = _render_dynamic_field(
                        parameter,
                        options,
                        _dynamic_project_value(attributes, parameter),
                        key_prefix,
                    )
    return values


@st.dialog("Create new project", width="large")
def open_create_project_dialog(
    project_repo: ProjectRepository,
    schema_repo: SchemaRepository,
) -> None:
    """Create a project without leaving the Portfolio Overview."""
    project_id = project_repo.generate_project_id()
    groups = schema_repo.get_all_groups()
    type_repo = ProjectTypeRepository(project_repo.db_path)
    options = schema_repo.get_all_options()
    manager_options, manager_labels = _manager_options(project_repo)

    type_options = type_repo.get_all_types()
    type_labels = dict(zip(type_options["id"], type_options["name"]))
    type_id = st.selectbox(t("project_types.label"), list(type_labels), format_func=type_labels.get,
                          key=f"create_type_{project_id}")
    params = type_repo.get_template(int(type_id))
    defaults = {p["param_id"]: p["default_value"] for _, p in params.iterrows() if p["has_default"]}
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
            missing = SchemaService.validate_project_dynamic_attributes(dynamic_values, params)
            if not clean_name:
                st.error(t("master_data.err_required_fields"))
            elif missing:
                st.error("Missing mandatory attributes: " + ", ".join(missing))
            elif project_repo.exists(project_id):
                st.error(t("master_data.err_already_exists", id=str(project_id)))
            else:
                created_id = _save_project(project_repo.create_project,
                    project_id=project_id,
                    name=clean_name,
                    status=status,
                    planned_budget=planned,
                    actual_budget=actual,
                    dynamic_attributes=dynamic_values,
                    function_id=manager,
                    project_type_id=int(type_id),
                )
                st.session_state["selected_portfolio_project_id"] = created_id
                st.toast("Project created.", icon="✅")
                st.rerun()


@st.dialog("Edit project details", width="large")
def open_edit_project_dialog(
    project_id: int,
    project_repo: ProjectRepository,
    schema_repo: SchemaRepository,
) -> None:
    """Edit or delete one project without navigating to another page."""
    project = project_repo.get_project_by_id(project_id)
    if project is None:
        st.error("The selected project no longer exists.")
        return

    groups = schema_repo.get_all_groups()
    type_repo = ProjectTypeRepository(project_repo.db_path)
    options = schema_repo.get_all_options()
    manager_options, manager_labels = _manager_options(project_repo)
    current_manager = int(project.function_id) if project.function_id is not None else None
    manager_index = (
        manager_options.index(current_manager) if current_manager in manager_options else 0
    )

    type_options = type_repo.get_all_types()
    type_labels = dict(zip(type_options["id"], type_options["name"]))
    type_id = st.selectbox(t("project_types.label"), list(type_labels),
                          index=list(type_labels).index(project.project_type_id), format_func=type_labels.get,
                          key=f"edit_type_{project_id}")
    params = type_repo.get_template(int(type_id))
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
            missing = SchemaService.validate_project_dynamic_attributes(dynamic_values, params)
            if not clean_name:
                st.error(t("master_data.err_required_fields"))
            elif missing:
                st.error("Missing mandatory attributes: " + ", ".join(missing))
            else:
                _save_project(project_repo.update_project,
                    project_id=project_id,
                    name=clean_name,
                    status=status,
                    planned_budget=planned,
                    actual_budget=actual,
                    dynamic_attributes=dynamic_values,
                    function_id=manager,
                    project_type_id=int(type_id),
                )
                st.toast("Project details updated.", icon="✅")
                st.rerun()

    st.divider()
    with st.expander("Delete project"):
        st.warning("Deleting a project also removes its tasks and dependencies.")
        confirmed = st.checkbox(
            f"I confirm deletion of {project.name}",
            key=f"portfolio_confirm_delete_{project_id}",
        )
        if st.button(
            "Delete project",
            icon=":material/delete:",
            type="primary",
            disabled=not confirmed,
            key=f"portfolio_delete_project_{project_id}",
        ):
            project_repo.delete_project(project_id)
            if str(st.session_state.get("selected_portfolio_project_id")) == str(project_id):
                st.session_state.pop("selected_portfolio_project_id", None)
            st.toast("Project deleted.", icon="✅")
            st.rerun()
