import datetime
import json
from typing import Any, Optional

import pandas as pd
import streamlit as st

from src.i18n import t
from src.models.constants import (
    PARAM_TYPE_ENUM,
    PARAM_TYPE_MULTI_ENUM,
    PARAM_TYPE_TAGS,
    PARAM_TYPE_TEXT,
    PARAM_TYPE_URL,
    STATUS_LIST,
)
from src.models.resource_pool import PoolAssignment
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.resource_pool_repo import ResourcePoolRepository
from src.repositories.schema_repo import SchemaRepository
from src.services.resource_pool_service import ResourcePoolService


def render_project_master(
    project_repo: ProjectRepository,
    schema_repo: SchemaRepository,
    pool_repo: Optional[ResourcePoolRepository] = None,
    milestone_repo: Optional[MilestoneRepository] = None,
) -> None:
    """Renders the Project Master Data screen for creating, editing, and deleting projects."""
    st.header(f"📋 {t('master_data.title')}")

    pool_repo = pool_repo or ResourcePoolRepository(project_repo.db_path)
    milestone_repo = milestone_repo or MilestoneRepository(project_repo.db_path)
    org_repo = OrganizationRepository(project_repo.db_path)


    tab_create, tab_edit = st.tabs([t("master_data.tab_create"), t("master_data.tab_edit")])
    groups = schema_repo.get_all_groups()
    params = schema_repo.get_all_parameters()
    options = schema_repo.get_all_options()

    # --------------------------------------------------------------------------
    # TAB 1: CREATE PROJECT
    # --------------------------------------------------------------------------
    with tab_create:
        st.subheader(t("master_data.create_header"))
        auto_id = project_repo.generate_project_id()
        with st.form("form_create_project", clear_on_submit=True):
            col1, col2 = st.columns(2)
            col1.text_input(
                t("master_data.field_id"),
                value=str(auto_id),
                disabled=True,
                help=t("master_data.field_id_help"),
            )
            new_name = col2.text_input(t("master_data.field_name"), placeholder=t("master_data.field_name_placeholder"))

            col3, col4, col5 = st.columns(3)
            new_status = col3.selectbox(t("master_data.field_status"), options=STATUS_LIST, index=0)
            new_planned = col4.number_input(t("master_data.field_planned"), min_value=0.0, value=150000.0, step=5000.0)
            new_actual = col5.number_input(t("master_data.field_actual"), min_value=0.0, value=0.0, step=5000.0)

            st.write(f"#### {t('master_data.dynamic_section')}")
            dyn_values: dict[str, Any] = {}

            if params.empty:
                st.caption(t("master_data.dynamic_empty"))
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
                    with st.expander(f"📌 {t('schema.param_group_none')}", expanded=True):
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

            btn_submit = st.form_submit_button(t("master_data.btn_save_new"), width="stretch")
            if btn_submit:
                clean_name = new_name.strip()

                if not clean_name:
                    st.error(t("master_data.err_required_fields"))
                elif project_repo.exists(auto_id):
                    st.error(t("master_data.err_already_exists", id=str(auto_id)))
                else:
                    new_proj_id = project_repo.create_project(
                        project_id=auto_id,
                        name=clean_name,
                        status=new_status,
                        planned_budget=new_planned,
                        actual_budget=new_actual,
                        dynamic_attributes=dyn_values,
                    )
                    st.success(t("master_data.msg_created_success", id=str(new_proj_id), name=clean_name))
                    st.rerun()

    # --------------------------------------------------------------------------
    # TAB 2: EDIT / DELETE PROJECT
    # --------------------------------------------------------------------------
    with tab_edit:
        st.subheader(t("master_data.edit_header"))
        df_existing = project_repo.get_all_projects()

        if df_existing.empty:
            st.info(t("master_data.dynamic_empty", default="No projects available to edit."))
            return

        proj_options = df_existing["id"].tolist()
        proj_map = dict(zip(df_existing["id"], df_existing["name"]))
        target_pid = st.session_state.pop("target_edit_project_id", None)
        default_idx = 0
        if target_pid is not None:
            for idx, p_opt in enumerate(proj_options):
                if str(p_opt) == str(target_pid):
                    default_idx = idx
                    break
        elif "sb_edit_project_id" in st.session_state and st.session_state["sb_edit_project_id"] in proj_options:
            default_idx = proj_options.index(st.session_state["sb_edit_project_id"])

        selected_id = st.selectbox(
            t("master_data.select_project"),
            options=proj_options,
            index=default_idx,
            key="sb_edit_project_id",
            format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
        )

        curr_row = df_existing[df_existing["id"] == selected_id].iloc[0]
        try:
            curr_dyn = json.loads(curr_row["dynamic_attributes"]) if curr_row["dynamic_attributes"] else {}
        except (json.JSONDecodeError, TypeError):
            curr_dyn = {}

        with st.form("form_edit_project"):
            col_id, col1, col2 = st.columns([1, 2, 1])
            col_id.text_input(t("master_data.field_id"), value=selected_id, disabled=True)
            edit_name = col1.text_input(t("master_data.field_name"), value=str(curr_row["name"]))
            edit_status_idx = STATUS_LIST.index(curr_row["status"]) if curr_row["status"] in STATUS_LIST else 0
            edit_status = col2.selectbox(t("master_data.field_status"), options=STATUS_LIST, index=edit_status_idx)

            col3, col4 = st.columns(2)
            edit_planned = col3.number_input(
                t("master_data.field_planned"),
                min_value=0.0,
                value=float(curr_row["planned_budget"]),
                step=5000.0,
            )
            edit_actual = col4.number_input(
                t("master_data.field_actual"),
                min_value=0.0,
                value=float(curr_row["actual_budget"]),
                step=5000.0,
            )

            st.write(f"#### {t('master_data.dynamic_section')}")
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
                    with st.expander(f"📌 {t('schema.param_group_none')}", expanded=True):
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

            btn_update = st.form_submit_button(t("master_data.btn_update"), width="stretch")
            if btn_update:
                if not edit_name.strip():
                    st.error(t("master_data.err_required_fields"))
                else:
                    project_repo.update_project(
                        project_id=selected_id,
                        name=edit_name.strip(),
                        status=edit_status,
                        planned_budget=edit_planned,
                        actual_budget=edit_actual,
                        dynamic_attributes=edit_dyn_values,
                    )
                    st.success(t("master_data.msg_updated_success", id=selected_id))
                    st.rerun()

        st.divider()

        # Resource Pool Allocations Section
        st.write("#### 🏊 Resource Pool Allocations")
        df_proj_assign = pool_repo.get_assignments(project_id=selected_id)
        if df_proj_assign.empty:
            st.info("No resource pools currently assigned to this project.")
        else:
            proj_assign_rows = []
            for _, r_a in df_proj_assign.iterrows():
                a_pid = int(r_a["pool_id"])
                p_status = ResourcePoolService.calculate_project_pool_status(
                    selected_id, a_pid, org_repo, pool_repo, milestone_repo
                )
                status_label = (
                    f"⚠️ OVERASSIGNED (+{p_status['excess_fte']:.2f} FTE)"
                    if p_status["is_overassigned"]
                    else "✅ OK"
                )
                period_str = f"{r_a['effective_start_date'] or '—'} → {r_a['effective_end_date'] or '—'}"
                if pd.notna(r_a.get("custom_start_date")):
                    period_str += " (Custom Period)"
                else:
                    period_str += " (Full Period)"

                proj_assign_rows.append({
                    "ID": int(r_a["id"]),
                    "Pool Name": str(r_a["pool_name"]),
                    "Target Scope": str(r_a["task_name"]) if pd.notna(r_a.get("task_name")) else "Project Level",
                    "Assigned FTE": f"{float(r_a['fte_assigned']):.2f} FTE",
                    "Period": period_str,
                    "Daily Status": status_label,
                    "Notes": str(r_a.get("notes") or ""),
                })

            c_tbl, c_del = st.columns([5, 1])
            with c_tbl:
                st.dataframe(pd.DataFrame(proj_assign_rows), use_container_width=True, hide_index=True)
            with c_del:
                del_a_opts = df_proj_assign["id"].tolist()
                del_aid = st.selectbox("Unassign", options=del_a_opts, key=f"sb_del_proj_assign_{selected_id}", label_visibility="collapsed")
                if st.button("🗑️ Unassign", key=f"btn_unassign_proj_{selected_id}"):
                    pool_repo.delete_assignment(del_aid)
                    st.toast(f"Assignment #{del_aid} removed.", icon="🗑️")
                    st.rerun()

        # Add Assignment Expander
        df_all_pools = pool_repo.get_all_pools()
        if not df_all_pools.empty:
            with st.expander("➕ Assign Resource Pool to Project", expanded=False):
                with st.form(f"form_assign_pool_proj_{selected_id}"):
                    pool_map = dict(zip(df_all_pools["id"], df_all_pools["name"]))
                    sel_pool_id = st.selectbox(
                        "Select Resource Pool",
                        options=df_all_pools["id"].tolist(),
                        format_func=lambda x: f"🏊 #{x} - {pool_map.get(x, '')}",
                    )
                    sel_fte = st.number_input("Assigned FTE", min_value=0.1, max_value=100.0, value=1.0, step=0.5)

                    period_mode = st.radio(
                        "Assignment Period Mode",
                        options=["full", "custom"],
                        format_func=lambda x: "Full Project Period (Default)" if x == "full" else "Custom Date Range",
                        horizontal=True,
                    )

                    c_d1, c_d2 = st.columns(2)
                    c_start_val: Optional[str] = None
                    c_end_val: Optional[str] = None
                    if period_mode == "custom":
                        d_start = c_d1.date_input("Start Date", value=datetime.date.today())
                        d_end = c_d2.date_input("End Date", value=datetime.date.today() + datetime.timedelta(days=30))
                        c_start_val = d_start.isoformat()
                        c_end_val = d_end.isoformat()

                    assign_notes = st.text_input("Notes / Role Description (Optional)")

                    if st.form_submit_button("💾 Save Allocation"):
                        pool_repo.create_assignment(
                            PoolAssignment(
                                pool_id=int(sel_pool_id),
                                project_id=selected_id,
                                task_id=None,
                                fte_assigned=float(sel_fte),
                                start_date=c_start_val,
                                end_date=c_end_val,
                                notes=assign_notes.strip(),
                            )
                        )
                        st.toast("Resource pool assigned to project!", icon="✅")
                        st.rerun()

        st.divider()
        st.write("#### ⚠️ Danger Zone")
        col_del1, col_del2 = st.columns([3, 1])
        confirm_del = col_del1.checkbox(f"{t('master_data.confirm_delete')}: '{selected_id}'")
        if col_del2.button(t("master_data.btn_delete"), type="secondary", disabled=not confirm_del):
            project_repo.delete_project(selected_id)
            st.success(t("master_data.msg_deleted_success", id=selected_id))
            st.rerun()
