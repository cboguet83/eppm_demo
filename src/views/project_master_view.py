"""Screen 2: Project Master Data View."""

import json
from typing import Any

import pandas as pd
import streamlit as st

from src.models.constants import (
    PARAM_TYPE_ENUM,
    PARAM_TYPE_MULTI_ENUM,
    PARAM_TYPE_TAGS,
    PARAM_TYPE_TEXT,
    PARAM_TYPE_URL,
    STATUS_LIST,
)
from src.repositories.project_repo import ProjectRepository
from src.repositories.schema_repo import SchemaRepository


def render_project_master(
    project_repo: ProjectRepository,
    schema_repo: SchemaRepository,
) -> None:
    """Renders the Project Master Data screen for creating, editing, and deleting projects."""
    st.header("📋 Project Master Data")

    tab_create, tab_edit = st.tabs(["➕ Create New Project", "✏️ Edit / Delete Existing Project"])
    groups = schema_repo.get_all_groups()
    params = schema_repo.get_all_parameters()
    options = schema_repo.get_all_options()

    # --------------------------------------------------------------------------
    # TAB 1: CREATE PROJECT
    # --------------------------------------------------------------------------
    with tab_create:
        st.subheader("Create a New Project")
        with st.form("form_create_project", clear_on_submit=True):
            col1, col2 = st.columns(2)
            new_id = col1.text_input("Project Code / ID *", placeholder="e.g. PRJ-006")
            new_name = col2.text_input("Project Title *", placeholder="e.g. Cloud Data Lake Platform")

            col3, col4, col5 = st.columns(3)
            new_status = col3.selectbox("Status", options=STATUS_LIST, index=0)
            new_planned = col4.number_input("Planned Budget ($)", min_value=0.0, value=150000.0, step=5000.0)
            new_actual = col5.number_input("Actual Spend ($)", min_value=0.0, value=0.0, step=5000.0)

            st.write("#### 🧩 Dynamic Schema Attributes")
            dyn_values: dict[str, Any] = {}

            if params.empty:
                st.caption("No dynamic schema parameters configured. Add parameters in 'Parameters Definition'.")
            else:
                # Render Grouped Parameters
                if not groups.empty:
                    for _, grp in groups.iterrows():
                        gid = grp["id"]
                        gname = grp["group_name"]
                        grp_params = params[params["group_id"] == gid]
                        if grp_params.empty:
                            continue

                        with st.expander(f"📁 {gname}", expanded=True):
                            for _, p in grp_params.iterrows():
                                pid = str(p["param_id"])
                                pname = str(p["param_name"])
                                ptype = str(p["param_type"])

                                if ptype == PARAM_TYPE_TEXT:
                                    dyn_values[pid] = st.text_input(pname, key=f"create_{pid}")
                                elif ptype == PARAM_TYPE_URL:
                                    dyn_values[pid] = st.text_input(pname, placeholder="https://...", key=f"create_{pid}")
                                elif ptype == PARAM_TYPE_ENUM:
                                    p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                                    dyn_values[pid] = st.selectbox(pname, options=[""] + p_opts, key=f"create_{pid}")
                                elif ptype in (PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS):
                                    p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                                    dyn_values[pid] = st.multiselect(f"{pname} ({ptype})", options=p_opts, key=f"create_{pid}")

                # Render Ungrouped Parameters
                ungrouped_params = params[params["group_id"].isna() | (params["group_id"] == None)]  # noqa: E711
                if not ungrouped_params.empty:
                    with st.expander("📌 General Attributes (No Group Assigned)", expanded=True):
                        for _, p in ungrouped_params.iterrows():
                            pid = str(p["param_id"])
                            pname = str(p["param_name"])
                            ptype = str(p["param_type"])

                            if ptype == PARAM_TYPE_TEXT:
                                dyn_values[pid] = st.text_input(pname, key=f"create_{pid}")
                            elif ptype == PARAM_TYPE_URL:
                                dyn_values[pid] = st.text_input(pname, placeholder="https://...", key=f"create_{pid}")
                            elif ptype == PARAM_TYPE_ENUM:
                                p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                                dyn_values[pid] = st.selectbox(pname, options=[""] + p_opts, key=f"create_{pid}")
                            elif ptype in (PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS):
                                p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                                dyn_values[pid] = st.multiselect(f"{pname} ({ptype})", options=p_opts, key=f"create_{pid}")

            btn_submit = st.form_submit_button("💾 Save New Project", width="stretch")
            if btn_submit:
                clean_id = new_id.strip()
                clean_name = new_name.strip()

                if not clean_id or not clean_name:
                    st.error("Project Code and Project Title are required.")
                elif project_repo.exists(clean_id):
                    st.error(f"Project with Code '{clean_id}' already exists. Use a unique Code.")
                else:
                    project_repo.create_project(
                        project_id=clean_id,
                        name=clean_name,
                        status=new_status,
                        planned_budget=new_planned,
                        actual_budget=new_actual,
                        dynamic_attributes=dyn_values,
                    )
                    st.success(f"Project '{clean_id} - {clean_name}' created successfully!")
                    st.rerun()

    # --------------------------------------------------------------------------
    # TAB 2: EDIT / DELETE PROJECT
    # --------------------------------------------------------------------------
    with tab_edit:
        st.subheader("Manage Existing Project")
        df_existing = project_repo.get_all_projects()

        if df_existing.empty:
            st.info("No projects available to edit.")
            return

        proj_options = df_existing["id"].tolist()
        proj_map = dict(zip(df_existing["id"], df_existing["name"]))

        selected_id = st.selectbox(
            "Select Project",
            options=proj_options,
            format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
        )

        curr_row = df_existing[df_existing["id"] == selected_id].iloc[0]
        try:
            curr_dyn = json.loads(curr_row["dynamic_attributes"]) if curr_row["dynamic_attributes"] else {}
        except (json.JSONDecodeError, TypeError):
            curr_dyn = {}

        with st.form("form_edit_project"):
            col1, col2 = st.columns(2)
            edit_name = col1.text_input("Project Title *", value=str(curr_row["name"]))
            edit_status_idx = STATUS_LIST.index(curr_row["status"]) if curr_row["status"] in STATUS_LIST else 0
            edit_status = col2.selectbox("Status", options=STATUS_LIST, index=edit_status_idx)

            col3, col4 = st.columns(2)
            edit_planned = col3.number_input(
                "Planned Budget ($)",
                min_value=0.0,
                value=float(curr_row["planned_budget"]),
                step=5000.0,
            )
            edit_actual = col4.number_input(
                "Actual Spend ($)",
                min_value=0.0,
                value=float(curr_row["actual_budget"]),
                step=5000.0,
            )

            st.write("#### 🧩 Dynamic Schema Attributes")
            edit_dyn_values: dict[str, Any] = {}

            if not params.empty:
                # Grouped parameters
                if not groups.empty:
                    for _, grp in groups.iterrows():
                        gid = grp["id"]
                        gname = grp["group_name"]
                        grp_params = params[params["group_id"] == gid]
                        if grp_params.empty:
                            continue

                        with st.expander(f"📁 {gname}", expanded=True):
                            for _, p in grp_params.iterrows():
                                pid = str(p["param_id"])
                                pname = str(p["param_name"])
                                ptype = str(p["param_type"])
                                val = curr_dyn.get(pid)

                                if ptype == PARAM_TYPE_TEXT:
                                    edit_dyn_values[pid] = st.text_input(
                                        pname,
                                        value=str(val) if val is not None else "",
                                        key=f"edit_{pid}",
                                    )
                                elif ptype == PARAM_TYPE_URL:
                                    edit_dyn_values[pid] = st.text_input(
                                        pname,
                                        value=str(val) if val is not None else "",
                                        placeholder="https://...",
                                        key=f"edit_{pid}",
                                    )
                                elif ptype == PARAM_TYPE_ENUM:
                                    p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                                    all_opts = [""] + p_opts
                                    cur_idx = all_opts.index(val) if val in all_opts else 0
                                    edit_dyn_values[pid] = st.selectbox(
                                        pname,
                                        options=all_opts,
                                        index=cur_idx,
                                        key=f"edit_{pid}",
                                    )
                                elif ptype in (PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS):
                                    p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                                    cur_multi = val if isinstance(val, list) else ([val] if val else [])
                                    valid_opts = sorted(list(set(p_opts + cur_multi)))
                                    edit_dyn_values[pid] = st.multiselect(
                                        f"{pname} ({ptype})",
                                        options=valid_opts,
                                        default=[o for o in cur_multi if o in valid_opts],
                                        key=f"edit_{pid}",
                                    )

                # Ungrouped parameters
                ungrouped_params = params[params["group_id"].isna() | (params["group_id"] == None)]  # noqa: E711
                if not ungrouped_params.empty:
                    with st.expander("📌 General Attributes (No Group Assigned)", expanded=True):
                        for _, p in ungrouped_params.iterrows():
                            pid = str(p["param_id"])
                            pname = str(p["param_name"])
                            ptype = str(p["param_type"])
                            val = curr_dyn.get(pid)

                            if ptype == PARAM_TYPE_TEXT:
                                edit_dyn_values[pid] = st.text_input(
                                    pname,
                                    value=str(val) if val is not None else "",
                                    key=f"edit_{pid}",
                                )
                            elif ptype == PARAM_TYPE_URL:
                                edit_dyn_values[pid] = st.text_input(
                                    pname,
                                    value=str(val) if val is not None else "",
                                    placeholder="https://...",
                                    key=f"edit_{pid}",
                                )
                            elif ptype == PARAM_TYPE_ENUM:
                                p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                                all_opts = [""] + p_opts
                                cur_idx = all_opts.index(val) if val in all_opts else 0
                                edit_dyn_values[pid] = st.selectbox(
                                    pname,
                                    options=all_opts,
                                    index=cur_idx,
                                    key=f"edit_{pid}",
                                )
                            elif ptype in (PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS):
                                p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                                cur_multi = val if isinstance(val, list) else ([val] if val else [])
                                valid_opts = sorted(list(set(p_opts + cur_multi)))
                                edit_dyn_values[pid] = st.multiselect(
                                    f"{pname} ({ptype})",
                                    options=valid_opts,
                                    default=[o for o in cur_multi if o in valid_opts],
                                    key=f"edit_{pid}",
                                )

            btn_update = st.form_submit_button("💾 Update Project Details", width="stretch")
            if btn_update:
                if not edit_name.strip():
                    st.error("Project Title is required.")
                else:
                    project_repo.update_project(
                        project_id=selected_id,
                        name=edit_name.strip(),
                        status=edit_status,
                        planned_budget=edit_planned,
                        actual_budget=edit_actual,
                        dynamic_attributes=edit_dyn_values,
                    )
                    st.success(f"Project '{selected_id}' updated successfully!")
                    st.rerun()

        st.divider()
        st.write("#### ⚠️ Danger Zone")
        col_del1, col_del2 = st.columns([3, 1])
        confirm_del = col_del1.checkbox(f"Confirm deletion of project '{selected_id}' and all its milestones")
        if col_del2.button("🗑️ Delete Project", type="secondary", disabled=not confirm_del):
            project_repo.delete_project(selected_id)
            st.success(f"Project '{selected_id}' deleted successfully.")
            st.rerun()
