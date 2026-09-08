"""Native configuration controls for project types and property applicability."""

import pandas as pd
import streamlit as st

from app.presentation.i18n import t
from app.application.services.project_types import ProjectTypeService
from app.application.exceptions import ProjectTypeStorageError
from app.presentation.components.project_type_frames import types_frame, template_frame
from app.presentation.components.dynamic_fields import render_dynamic_field


def applicability_input(
    service: ProjectTypeService, key: str, param_id: str | None = None,
) -> tuple[bool, list[int]]:
    """Collect property scope through application queries."""
    scope = service.get_applicability(param_id) if param_id else None
    all_types, selected = (scope.applies_to_all, list(scope.type_ids)) if scope else (True, [])
    types = types_frame(service.get_all_types())
    labels = dict(zip(types["id"], types["name"]))
    scope_labels = {
        True: t("project_types.all"),
        False: t("project_types.selected"),
    }
    mode = st.selectbox(t("project_types.applies_to"), [True, False], index=0 if all_types else 1,
                        format_func=scope_labels.get, key=f"{key}_scope")
    ids = st.multiselect(t("project_types.selected"), list(labels), default=selected,
                        format_func=labels.get, disabled=mode, key=f"{key}_types")
    return mode, ids


def render_project_types(service: ProjectTypeService, options: pd.DataFrame) -> None:
    """Render type management and rules using the injected application service."""
    with st.form("new_project_type"):
        name = st.text_input(t("project_types.name"))
        description = st.text_area(t("project_types.description"))
        if st.form_submit_button(t("project_types.create")):
            try:
                service.create_type(name, description)
                st.rerun()
            except (ValueError, ProjectTypeStorageError) as exc:
                st.error(str(exc))
    types = types_frame(service.get_all_types())
    labels = dict(zip(types["id"], types["name"]))
    type_id = st.selectbox(t("project_types.label"), list(labels), format_func=labels.get, key="template_type")
    row = types[types["id"] == type_id].iloc[0]
    with st.form(f"edit_type_{type_id}"):
        name = st.text_input(t("project_types.name"), value=row["name"], disabled=bool(row["is_general"]))
        description = st.text_area(t("project_types.description"), value=row["description"])
        if st.form_submit_button(t("project_types.save")):
            try:
                service.update_type(int(type_id), name, description)
                st.rerun()
            except (ValueError, ProjectTypeStorageError) as exc:
                st.error(str(exc))
    if st.button(t("project_types.delete"), disabled=bool(row["is_general"])):
        try:
            service.delete_type(int(type_id))
            st.rerun()
        except (ValueError, ProjectTypeStorageError) as exc:
            st.error(str(exc))
    st.subheader(t("project_types.template"))
    st.caption(t("project_types.builtin_fields"))
    template = template_frame(service.get_template(int(type_id)))
    if template.empty:
        st.info(t("project_types.no_properties"))
        return
    st.dataframe(template[["param_name", "param_type", "mandatory", "has_default", "default_value"]].assign(
        default_value=lambda frame: frame["default_value"].map(lambda value: "" if value is None else str(value))).rename(columns={
            "param_name": t("project_types.property"), "param_type": t("schema.param_type"),
            "mandatory": t("project_types.required"), "has_default": t("project_types.has_default"),
            "default_value": t("project_types.default_value"),
        }), hide_index=True)
    pid = st.selectbox(t("project_types.property"), template["param_id"].tolist(),
                       format_func=dict(zip(template["param_id"], template["param_name"])).get,
                       key=f"template_property_{type_id}")
    prop = template[template["param_id"] == pid].iloc[0]
    override = prop["mandatory_override"]
    current = "inherit" if pd.isna(override) else "required" if override else "optional"
    rule_labels = {
        value: t(f"project_types.{value}")
        for value in ("inherit", "required", "optional")
    }
    with st.container(border=True):
        rule = st.selectbox(t("project_types.required_rule"), ["inherit", "required", "optional"],
                            index=["inherit", "required", "optional"].index(current),
                            format_func=rule_labels.get, key=f"rule_{type_id}_{pid}")
        has_default = st.checkbox(t("project_types.has_default"), value=bool(prop["has_default"]), key=f"has_default_{type_id}_{pid}")
        default = render_dynamic_field(prop, options, prop["default_value"] if prop["has_default"] else None, f"default_{type_id}") if has_default else None
        st.caption(t("project_types.defaults_help"))
        if st.button(t("project_types.save_rule")):
            try:
                service.save_rule(int(type_id), pid, {"inherit": None, "required": True, "optional": False}[rule],
                               has_default=has_default, default_value=default)
                st.rerun()
            except (ValueError, ProjectTypeStorageError) as exc:
                st.error(str(exc))
