"""Screen 4: Planning & Step Loader View (Interactive Drag & Drop Gantt and Plotly Roadmap)."""

import datetime
import os
from typing import Any, Optional, Union

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from src.i18n import get_current_locale, get_section_catalog, t
from src.models.constants import PAGE_PROJECT_MASTER
from src.models.resource_pool import PoolAssignment
from src.models.tag import ProjectTag, TaskTag
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.resource_pool_repo import ResourcePoolRepository
from src.repositories.tag_repo import TagRepository
from src.services.milestone_service import MilestoneService
from src.services.resource_pool_service import ResourcePoolService

# Declare Frappe Gantt Custom Component
_COMPONENT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "components",
    "gantt",
)
_interactive_gantt = components.declare_component("interactive_gantt", path=_COMPONENT_PATH)


@st.dialog(t("planning.dialog_project_tags_title", default="🏷️ Manage Project Tags"))
def _manage_project_tags_dialog(project_id: int, project_name: str, tag_repo: TagRepository) -> None:
    """Modal dialog for attaching, editing, and deleting tags on a project."""
    st.markdown(f"#### 📁 {project_name} `[#{project_id}]`")

    # 1. Existing Tags on Project
    df_current_tags = tag_repo.get_project_tags_by_project(project_id)
    st.markdown(f"##### {t('planning.current_tags', default='Current Assigned Tags')}")
    if df_current_tags.empty:
        st.info(t("planning.no_tags_assigned", default="No tags currently attached to this project."))
    else:
        for _, row in df_current_tags.iterrows():
            pt_id = int(row["id"])
            t_name = row.get("tag_name")
            g_name = row.get("tag_group_name")
            f_name = row.get("free_tag")
            display_label = f"🏷️ {t_name}" if pd.notna(t_name) and str(t_name).strip() else f"🏷️ {f_name}"
            if pd.notna(g_name) and str(g_name).strip():
                display_label = f"[{g_name}] {display_label}"

            c_tag, c_del = st.columns([4, 1])
            c_tag.markdown(
                f'<span style="background-color:#FDE8EC; color:#C41039; border:1px solid #C41039; padding:3px 10px; border-radius:12px; font-weight:600; font-size:12px; display:inline-block; margin-top:4px;">{escape_html(display_label) if "escape_html" in globals() else display_label}</span>',
                unsafe_allow_html=True,
            )
            if c_del.button("🗑️", key=f"btn_del_pt_{pt_id}", help="Remove tag from project"):
                tag_repo.delete_project_tag(pt_id)
                st.toast(t("planning.toast_tag_removed", default="Tag removed!"), icon="🗑️")
                st.rerun()

    st.divider()
    # 2. Attach New Tag
    st.markdown(f"##### ➕ {t('planning.attach_new_tag', default='Attach New Tag')}")
    df_tags = tag_repo.get_project_tag_group_tags()
    tag_options = [(None, t("planning.select_dict_tag_placeholder", default="-- Select from Tag Dictionary (Optional) --"))] + [
        (int(r["id"]), str(r["tag"]))
        for _, r in df_tags.iterrows()
    ]
    selected_tag_tuple = st.selectbox(
        t("planning.select_dict_tag", default="Dictionary Tag"),
        options=tag_options,
        format_func=lambda x: x[1],
        key="sb_attach_proj_tag",
    )
    selected_tag_id = selected_tag_tuple[0] if selected_tag_tuple else None

    free_tag_input = st.text_input(
        t("planning.free_tag_optional", default="Custom / Free Tag (Optional)"),
        placeholder="e.g. Q3-Priority, Pilot-Launch",
        key="ti_attach_proj_free_tag",
    )

    col_btn_save, col_btn_close = st.columns([3, 1])
    with col_btn_save:
        if st.button(t("planning.btn_attach_tag", default="Attach Tag"), type="primary", key="btn_confirm_attach_proj_tag"):
            if selected_tag_id is None and not free_tag_input.strip():
                st.error(t("planning.tag_required_error", default="Please select a dictionary tag or enter a custom tag."))
            else:
                tag_repo.create_project_tag(
                    ProjectTag(
                        project_id=project_id,
                        tag_id=selected_tag_id,
                        free_tag=free_tag_input.strip() if free_tag_input.strip() else None,
                    )
                )
                st.toast(t("planning.toast_tag_attached", default="Tag attached to project!"), icon="🏷️")
                st.rerun()

    with col_btn_close:
        if st.button(t("planning.btn_close_dialog", default="Close"), key="btn_close_proj_dialog"):
            st.rerun()


@st.dialog(t("planning.dialog_task_tags_title", default="🏷️ Manage Task Tags"))
def _manage_task_tags_dialog(task_id: int, task_name: str, tag_repo: TagRepository) -> None:
    """Modal dialog for adding, editing, and deleting tags on a task."""
    st.markdown(f"#### 📋 {task_name} `[Task #{task_id}]`")

    # 1. Existing Task Tags
    df_current_tags = tag_repo.get_task_tags_by_task(task_id)
    st.markdown(f"##### {t('planning.current_tags', default='Current Assigned Tags')}")
    if df_current_tags.empty:
        st.info(t("planning.no_task_tags_assigned", default="No tags currently attached to this task."))
    else:
        for _, row in df_current_tags.iterrows():
            tt_id = int(row["id"])
            t_name = row.get("tag_name")
            g_name = row.get("tag_group_name")
            f_name = row.get("free_tag")
            display_label = f"🏷️ {t_name}" if pd.notna(t_name) and str(t_name).strip() else f"🏷️ {f_name}"
            if pd.notna(g_name) and str(g_name).strip():
                display_label = f"[{g_name}] {display_label}"

            c_tag, c_del = st.columns([4, 1])
            c_tag.markdown(f"**{display_label}**")
            if c_del.button("🗑️", key=f"btn_del_tt_{tt_id}", help="Remove tag from task"):
                tag_repo.delete_task_tag(tt_id)
                st.toast(t("planning.toast_task_tag_removed", default="Task tag removed!"), icon="🗑️")
                st.rerun()

    st.divider()
    # 2. Attach New Tag to Task
    st.markdown(f"##### ➕ {t('planning.attach_new_task_tag', default='Attach New Tag to Task')}")
    df_tags = tag_repo.get_task_tag_group_tags()
    tag_options = [(None, t("planning.select_dict_tag_placeholder", default="-- Select from Tag Dictionary (Optional) --"))] + [
        (int(r["id"]), str(r["tag"]))
        for _, r in df_tags.iterrows()
    ]
    selected_tag_tuple = st.selectbox(
        t("planning.select_dict_tag", default="Dictionary Tag"),
        options=tag_options,
        format_func=lambda x: x[1],
        key="sb_attach_task_tag",
    )
    selected_tag_id = selected_tag_tuple[0] if selected_tag_tuple else None

    free_tag_input = st.text_input(
        t("planning.free_tag_optional", default="Custom / Free Tag (Optional)"),
        placeholder="e.g. Critical-Path, Security-Review",
        key="ti_attach_task_free_tag",
    )

    col_btn_save, col_btn_close = st.columns([3, 1])
    with col_btn_save:
        if st.button(t("planning.btn_attach_tag", default="Attach Tag"), type="primary", key="btn_confirm_attach_task_tag"):
            if selected_tag_id is None and not free_tag_input.strip():
                st.error(t("planning.tag_required_error", default="Please select a dictionary tag or enter a custom tag."))
            else:
                tag_repo.create_task_tag(
                    TaskTag(
                        task_id=task_id,
                        tag_id=selected_tag_id,
                        free_tag=free_tag_input.strip() if free_tag_input.strip() else None,
                    )
                )
                st.toast(t("planning.toast_task_tag_attached", default="Tag attached to task!"), icon="🏷️")
                st.rerun()

    with col_btn_close:
        if st.button(t("planning.btn_close_dialog", default="Close"), key="btn_close_task_dialog"):
            st.session_state["modal_manage_task_tag"] = None
            st.rerun()


@st.dialog(t("planning.dialog_project_pools_title", default="🏊 Manage Project Resource Pools"))
def _manage_project_resource_pools_dialog(
    project_id: int,
    project_name: str,
    pool_repo: ResourcePoolRepository,
    milestone_repo: MilestoneRepository,
    org_repo: Optional[OrganizationRepository] = None,
) -> None:
    """Modal dialog for viewing, allocating, and unassigning resource pools at project level."""
    if org_repo is None:
        org_repo = OrganizationRepository(pool_repo.db_path)
    st.markdown(f"#### 📁 {project_name} `[Project #{project_id}]`")

    # Fetch project date bounds
    proj_bounds = milestone_repo.get_all_project_date_bounds()
    p_bound = proj_bounds.get(project_id) or proj_bounds.get(str(project_id)) or (None, None)
    p_start_str, p_end_str = p_bound
    if p_start_str and p_end_str:
        st.caption(f"📅 **Project Timeline:** `{p_start_str}` ➔ `{p_end_str}`")

    # 1. Existing Project-Level Pool Assignments
    df_current_assigns = pool_repo.get_assignments(project_id=project_id, only_project_level=True)
    st.markdown(f"##### {t('planning.current_pools', default='Current Assigned Resource Pools')}")

    if df_current_assigns.empty:
        st.info(t("planning.no_pools_assigned_project", default="No resource pools currently assigned to this project."))
    else:
        for _, row in df_current_assigns.iterrows():
            assign_id = int(row["id"])
            p_id = int(row["pool_id"])
            p_name = str(row["pool_name"])
            fte_val = float(row["fte_assigned"])
            c_start = row.get("custom_start_date")
            c_end = row.get("custom_end_date")

            # Check capacity and daily overassignment status
            cap_detail = ResourcePoolService.calculate_pool_capacity(p_id, org_repo, pool_repo, milestone_repo)
            p_status = ResourcePoolService.calculate_project_pool_status(project_id, p_id, org_repo, pool_repo, milestone_repo)

            if p_status["is_overassigned"]:
                status_html = f'<span style="background-color:#FDE8EC; color:#C41039; border:1px solid #C41039; padding:2px 7px; border-radius:10px; font-weight:700; font-size:11px;">⚠️ Overassigned (Peak: {p_status["project_peak_assigned_fte"]:.2f} / Cap: {cap_detail.total_capacity_fte:.2f} FTE)</span>'
            else:
                status_html = f'<span style="background-color:#ECFDF5; color:#047857; border:1px solid #10B981; padding:2px 7px; border-radius:10px; font-weight:700; font-size:11px;">✅ OK (Peak: {p_status["project_peak_assigned_fte"]:.2f} / Cap: {cap_detail.total_capacity_fte:.2f} FTE)</span>'

            if pd.notna(c_start) and pd.notna(c_end) and str(c_start).strip() and str(c_end).strip():
                period_str = f"📅 {c_start} to {c_end} *(Custom Period)*"
            else:
                period_str = f"📅 Full Project Duration ({p_start_str or 'Start'} to {p_end_str or 'End'})"

            c_info, c_del = st.columns([5, 1])
            with c_info:
                st.markdown(
                    f'<div style="background:#F8FAFC; border:1px solid #E2E8F0; border-left:4px solid #0284C7; padding:8px 10px; border-radius:6px; margin-bottom:6px;">'
                    f'<div style="display:flex; justify-content:space-between; align-items:center;">'
                    f'<b style="color:#0F172A; font-size:13px;">🏊 {p_name}</b>'
                    f'<span style="font-weight:700; color:#0284C7; font-size:12px;">{fte_val:.2f} FTE</span>'
                    f'</div>'
                    f'<div style="font-size:11.5px; color:#475569; margin-top:3px;">{period_str}</div>'
                    f'<div style="margin-top:4px;">{status_html}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with c_del:
                if st.button("🗑️", key=f"btn_del_assign_proj_{assign_id}", help=t("planning.btn_unassign_pool", default="Remove pool assignment")):
                    pool_repo.delete_assignment(assign_id)
                    st.toast(t("planning.toast_pool_unassigned_proj", default="Project pool assignment removed!"), icon="🗑️")
                    st.rerun()

    st.divider()

    # 2. Assign a Resource Pool to Project
    st.markdown(f"##### ➕ {t('planning.assign_new_pool', default='Assign Resource Pool')}")
    df_all_pools = pool_repo.get_all_pools()
    if df_all_pools.empty:
        st.warning(t("planning.no_pools_exist", default="No resource pools configured. Create pools in Settings > Resource Pools."))
        return

    pool_choices = []
    for _, pr in df_all_pools.iterrows():
        pid = int(pr["id"])
        pcap = ResourcePoolService.calculate_pool_capacity(pid, org_repo, pool_repo, milestone_repo)
        pool_choices.append((pid, f"🏊 {pr['name']} (Cap: {pcap.total_capacity_fte:.2f} FTE)"))

    sel_pool_tuple = st.selectbox(
        t("planning.select_resource_pool", default="Select Resource Pool *"),
        options=pool_choices,
        format_func=lambda x: x[1],
        key="sb_assign_proj_pool",
    )
    sel_pool_id = sel_pool_tuple[0] if sel_pool_tuple else None

    c_fte, c_mode = st.columns([1, 2])
    with c_fte:
        fte_input = st.number_input(
            t("master_data.field_fte", default="Assigned FTE *"),
            min_value=0.1,
            max_value=100.0,
            value=1.0,
            step=0.1,
            key="ni_assign_proj_fte",
        )
    with c_mode:
        period_mode = st.radio(
            t("master_data.assignment_period_mode", default="Assignment Period Mode"),
            options=["full", "custom"],
            format_func=lambda m: (
                t("master_data.period_full_project", default="Full Project Duration (Default)")
                if m == "full"
                else t("master_data.period_custom_range", default="Custom Specific Period")
            ),
            key="rb_assign_proj_period_mode",
            horizontal=True,
        )

    custom_start_str = None
    custom_end_str = None
    if period_mode == "custom":
        default_s = (
            datetime.datetime.strptime(p_start_str, "%Y-%m-%d").date()
            if p_start_str
            else datetime.date.today()
        )
        default_e = (
            datetime.datetime.strptime(p_end_str, "%Y-%m-%d").date()
            if p_end_str
            else (default_s + datetime.timedelta(days=30))
        )
        col_s, col_e = st.columns(2)
        with col_s:
            custom_s_val = st.date_input(t("master_data.custom_start_date", default="Start Date"), value=default_s, key="di_assign_proj_s")
        with col_e:
            custom_e_val = st.date_input(t("master_data.custom_end_date", default="End Date"), value=default_e, key="di_assign_proj_e")

        if custom_s_val and custom_e_val:
            if custom_e_val < custom_s_val:
                st.error(t("master_data.date_range_error", default="End Date cannot be before Start Date."))
            else:
                custom_start_str = custom_s_val.strftime("%Y-%m-%d")
                custom_end_str = custom_e_val.strftime("%Y-%m-%d")

    notes_input = st.text_input(
        t("master_data.field_assignment_notes", default="Notes / Allocation Purpose"),
        placeholder="e.g. Core architectural oversight, PMO support",
        key="ti_assign_proj_notes",
    )

    col_btn_save, col_btn_close = st.columns([3, 1])
    with col_btn_save:
        if st.button(t("planning.btn_confirm_assign_pool_proj", default="Assign Pool to Project"), type="primary", key="btn_confirm_assign_proj_pool"):
            if sel_pool_id is None:
                st.error(t("planning.pool_required_error", default="Please select a resource pool."))
            elif period_mode == "custom" and (not custom_start_str or not custom_end_str):
                st.error(t("master_data.date_range_error", default="End Date cannot be before Start Date."))
            else:
                new_assignment = PoolAssignment(
                    pool_id=sel_pool_id,
                    project_id=project_id,
                    task_id=None,
                    fte_assigned=float(fte_input),
                    start_date=custom_start_str,
                    end_date=custom_end_str,
                    notes=notes_input.strip(),
                )
                pool_repo.create_assignment(new_assignment)
                st.toast(t("planning.toast_pool_assigned_proj", default="Resource pool assigned to project!"), icon="🏊")
                st.session_state["modal_manage_project_pool"] = None
                st.rerun()

    with col_btn_close:
        if st.button(t("planning.btn_close_dialog", default="Close"), key="btn_close_proj_pool_dialog"):
            st.session_state["modal_manage_project_pool"] = None
            st.rerun()


@st.dialog(t("planning.dialog_task_pools_title", default="🏊 Manage Task Resource Pools"))
def _manage_task_resource_pools_dialog(
    task_id: int,
    task_name: str,
    project_id: Union[int, str],
    pool_repo: ResourcePoolRepository,
    milestone_repo: MilestoneRepository,
    org_repo: Optional[OrganizationRepository] = None,
) -> None:
    """Modal dialog for viewing, assigning, and removing resource pools on a task."""
    if org_repo is None:
        org_repo = OrganizationRepository(pool_repo.db_path)
    st.markdown(f"#### 📋 {task_name} `[Task #{task_id}]` (Project #{project_id})")

    # Fetch task dates for reference and defaults
    step_info = milestone_repo.get_milestone_by_id(task_id)
    task_start_str = step_info.get("start_date") if step_info else None
    task_end_str = step_info.get("end_date") if step_info else None
    if task_start_str and task_end_str:
        st.caption(f"📅 **Task Schedule:** `{task_start_str}` ➔ `{task_end_str}`")

    # 1. Existing Pool Assignments on this task
    df_current_assigns = pool_repo.get_assignments(task_id=task_id)
    st.markdown(f"##### {t('planning.current_pools', default='Current Assigned Resource Pools')}")

    if df_current_assigns.empty:
        st.info(t("planning.no_pools_assigned_task", default="No resource pools currently assigned to this task."))
    else:
        for _, row in df_current_assigns.iterrows():
            assign_id = int(row["id"])
            p_id = int(row["pool_id"])
            p_name = str(row["pool_name"])
            fte_val = float(row["fte_assigned"])
            c_start = row.get("custom_start_date")
            c_end = row.get("custom_end_date")

            # Check capacity and daily overassignment status
            cap_detail = ResourcePoolService.calculate_pool_capacity(p_id, org_repo, pool_repo, milestone_repo)
            if cap_detail.is_overassigned:
                status_html = f'<span style="background-color:#FDE8EC; color:#C41039; border:1px solid #C41039; padding:2px 7px; border-radius:10px; font-weight:700; font-size:11px;">⚠️ Overassigned (Peak: {cap_detail.peak_assigned_fte:.2f} / Cap: {cap_detail.total_capacity_fte:.2f} FTE)</span>'
            else:
                status_html = f'<span style="background-color:#ECFDF5; color:#047857; border:1px solid #10B981; padding:2px 7px; border-radius:10px; font-weight:700; font-size:11px;">✅ OK (Peak: {cap_detail.peak_assigned_fte:.2f} / Cap: {cap_detail.total_capacity_fte:.2f} FTE)</span>'

            if pd.notna(c_start) and pd.notna(c_end) and str(c_start).strip() and str(c_end).strip():
                period_str = f"📅 {c_start} to {c_end} *(Custom Period)*"
            else:
                period_str = f"📅 Full Task Duration ({task_start_str or 'Start'} to {task_end_str or 'End'})"

            c_info, c_del = st.columns([5, 1])
            with c_info:
                st.markdown(
                    f'<div style="background:#F8FAFC; border:1px solid #E2E8F0; border-left:4px solid #0284C7; padding:8px 10px; border-radius:6px; margin-bottom:6px;">'
                    f'<div style="display:flex; justify-content:space-between; align-items:center;">'
                    f'<b style="color:#0F172A; font-size:13px;">🏊 {p_name}</b>'
                    f'<span style="font-weight:700; color:#0284C7; font-size:12px;">{fte_val:.2f} FTE</span>'
                    f'</div>'
                    f'<div style="font-size:11.5px; color:#475569; margin-top:3px;">{period_str}</div>'
                    f'<div style="margin-top:4px;">{status_html}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with c_del:
                if st.button("🗑️", key=f"btn_del_assign_task_{assign_id}", help=t("planning.btn_unassign_pool", default="Remove pool assignment")):
                    pool_repo.delete_assignment(assign_id)
                    st.toast(t("planning.toast_pool_unassigned", default="Pool assignment removed!"), icon="🗑️")
                    st.rerun()

    st.divider()

    # 2. Assign a Resource Pool
    st.markdown(f"##### ➕ {t('planning.assign_new_pool', default='Assign Resource Pool')}")
    df_all_pools = pool_repo.get_all_pools()
    if df_all_pools.empty:
        st.warning(t("planning.no_pools_exist", default="No resource pools configured. Create pools in Settings > Resource Pools."))
        return

    pool_choices = []
    for _, pr in df_all_pools.iterrows():
        pid = int(pr["id"])
        pcap = ResourcePoolService.calculate_pool_capacity(pid, org_repo, pool_repo, milestone_repo)
        pool_choices.append((pid, f"🏊 {pr['name']} (Cap: {pcap.total_capacity_fte:.2f} FTE)"))

    sel_pool_tuple = st.selectbox(
        t("planning.select_resource_pool", default="Select Resource Pool *"),
        options=pool_choices,
        format_func=lambda x: x[1],
        key="sb_assign_task_pool",
    )
    sel_pool_id = sel_pool_tuple[0] if sel_pool_tuple else None

    c_fte, c_mode = st.columns([1, 2])
    with c_fte:
        fte_input = st.number_input(
            t("master_data.field_fte", default="Assigned FTE *"),
            min_value=0.1,
            max_value=100.0,
            value=1.0,
            step=0.1,
            key="ni_assign_task_fte",
        )
    with c_mode:
        period_mode = st.radio(
            t("master_data.assignment_period_mode", default="Assignment Period Mode"),
            options=["full", "custom"],
            format_func=lambda m: (
                t("master_data.period_full_task", default="Full Task Duration (Default)")
                if m == "full"
                else t("master_data.period_custom_range", default="Custom Specific Period")
            ),
            key="rb_assign_task_period_mode",
            horizontal=True,
        )

    custom_start_str = None
    custom_end_str = None
    if period_mode == "custom":
        default_s = (
            datetime.datetime.strptime(task_start_str, "%Y-%m-%d").date()
            if task_start_str
            else datetime.date.today()
        )
        default_e = (
            datetime.datetime.strptime(task_end_str, "%Y-%m-%d").date()
            if task_end_str
            else (default_s + datetime.timedelta(days=14))
        )
        col_s, col_e = st.columns(2)
        with col_s:
            custom_s_val = st.date_input(t("master_data.custom_start_date", default="Start Date"), value=default_s, key="di_assign_task_s")
        with col_e:
            custom_e_val = st.date_input(t("master_data.custom_end_date", default="End Date"), value=default_e, key="di_assign_task_e")

        if custom_s_val and custom_e_val:
            if custom_e_val < custom_s_val:
                st.error(t("master_data.date_range_error", default="End Date cannot be before Start Date."))
            else:
                custom_start_str = custom_s_val.strftime("%Y-%m-%d")
                custom_end_str = custom_e_val.strftime("%Y-%m-%d")

    notes_input = st.text_input(
        t("master_data.field_assignment_notes", default="Notes / Allocation Purpose"),
        placeholder="e.g. Lead drafting, Structural analysis",
        key="ti_assign_task_notes",
    )

    col_btn_save, col_btn_close = st.columns([3, 1])
    with col_btn_save:
        if st.button(t("planning.btn_confirm_assign_pool", default="Assign Pool to Task"), type="primary", key="btn_confirm_assign_task_pool"):
            if sel_pool_id is None:
                st.error(t("planning.pool_required_error", default="Please select a resource pool."))
            elif period_mode == "custom" and (not custom_start_str or not custom_end_str):
                st.error(t("master_data.date_range_error", default="End Date cannot be before Start Date."))
            else:
                parsed_proj_id = int(project_id) if str(project_id).isdigit() else None
                new_assignment = PoolAssignment(
                    pool_id=sel_pool_id,
                    project_id=parsed_proj_id,
                    task_id=task_id,
                    fte_assigned=float(fte_input),
                    start_date=custom_start_str,
                    end_date=custom_end_str,
                    notes=notes_input.strip(),
                )
                pool_repo.create_assignment(new_assignment)
                st.toast(t("planning.toast_pool_assigned", default="Resource pool assigned to task!"), icon="🏊")
                st.session_state["modal_manage_task_pool"] = None
                st.rerun()

    with col_btn_close:
        if st.button(t("planning.btn_close_dialog", default="Close"), key="btn_close_task_pool_dialog"):
            st.session_state["modal_manage_task_pool"] = None
            st.rerun()


def render_planning_milestones(
    project_repo: ProjectRepository,
    milestone_repo: MilestoneRepository,
    tag_repo: Optional[TagRepository] = None,
    pool_repo: Optional[ResourcePoolRepository] = None,
    org_repo: Optional[OrganizationRepository] = None,
) -> None:
    """Renders the Planning & Step Loader screen with interactive drag & drop and Plotly timeline."""
    if tag_repo is None:
        tag_repo = TagRepository(project_repo.db_path)
    if pool_repo is None:
        pool_repo = ResourcePoolRepository(project_repo.db_path)
    if org_repo is None:
        org_repo = OrganizationRepository(project_repo.db_path)

    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 0.6rem !important;
            padding-bottom: 0.8rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            max-width: 100% !important;
        }
        h1, h2, h3 {
            margin-top: 0 !important;
            margin-bottom: 0.25rem !important;
            padding-top: 0 !important;
        }
        div[data-testid="stVerticalBlock"] > div {
            margin-bottom: 0.25rem !important;
        }
        /* Robust styling for multiselect selected item chips */
        div[data-baseweb="tag"],
        span[data-baseweb="tag"],
        [data-testid="stMultiSelect"] div[data-baseweb="tag"],
        [data-testid="stMultiSelect"] span[data-baseweb="tag"],
        [data-testid="stMultiSelectTag"],
        [data-baseweb="tag"] {
            background-color: #FDE8EC !important;
            background: #FDE8EC !important;
            border: 1px solid #C41039 !important;
            border-radius: 6px !important;
        }
        div[data-baseweb="tag"] *,
        span[data-baseweb="tag"] *,
        [data-testid="stMultiSelect"] div[data-baseweb="tag"] *,
        [data-testid="stMultiSelect"] span[data-baseweb="tag"] *,
        [data-testid="stMultiSelectTag"] * {
            color: #C41039 !important;
            fill: #C41039 !important;
        }
        div[data-baseweb="tag"] span,
        span[data-baseweb="tag"] span,
        [data-testid="stMultiSelect"] [data-baseweb="tag"] span {
            color: #C41039 !important;
            font-weight: 600 !important;
        }
        div[data-baseweb="tag"] svg,
        span[data-baseweb="tag"] svg,
        [data-baseweb="tag"] svg path {
            fill: #C41039 !important;
            color: #C41039 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    df_projects = project_repo.get_all_projects()

    if df_projects.empty:
        st.info(t("master_data.dynamic_empty", default="No projects registered yet."))
        return

    proj_map = dict(zip(df_projects["id"], df_projects["name"]))

    # --------------------------------------------------------------------------
    # TOP CONTROL: Project Tag Filter & Projects Multi-Selector
    # --------------------------------------------------------------------------
    df_all_proj_tags = tag_repo.get_all_project_tags()
    available_tags_set: set[str] = set()
    if not df_all_proj_tags.empty:
        for _, r in df_all_proj_tags.iterrows():
            t_name = r.get("tag_name")
            f_name = r.get("free_tag")
            if pd.notna(t_name) and str(t_name).strip():
                available_tags_set.add(str(t_name).strip())
            if pd.notna(f_name) and str(f_name).strip():
                available_tags_set.add(str(f_name).strip())

    available_tags_list = sorted(list(available_tags_set))

    # Check for external navigation focus (e.g. from Resource Pools table jump)
    target_pid = st.session_state.pop("target_planning_project_id", None)
    if target_pid is not None:
        try:
            target_pid_int = int(target_pid)
            st.session_state["ms_planning_tag_filter"] = []
            st.session_state["ms_multi_projects"] = [target_pid_int]
        except (ValueError, TypeError):
            pass

    top_filter_col, top_sel_col = st.columns([2, 3])

    with top_filter_col:
        selected_tag_filters = st.multiselect(
            f"🏷️ {t('planning.filter_by_tags', default='Filter Projects by Tag')}",
            options=available_tags_list,
            default=[],
            help="Filter project list to projects assigned any of the chosen tags.",
            key="ms_planning_tag_filter",
        )

    # Filter projects based on tag selection if any
    if selected_tag_filters and not df_all_proj_tags.empty:
        matching_proj_ids = set()
        for _, r in df_all_proj_tags.iterrows():
            t_name = str(r.get("tag_name", "")).strip()
            f_name = str(r.get("free_tag", "")).strip()
            if (t_name and t_name in selected_tag_filters) or (f_name and f_name in selected_tag_filters):
                matching_proj_ids.add(int(r["project_id"]))

        df_filtered_projects = df_projects[df_projects["id"].isin(matching_proj_ids)]
        if df_filtered_projects.empty:
            st.warning(t("planning.no_projects_matching_tags", default="No projects match the selected tag filter."))
        else:
            df_projects = df_filtered_projects

    if df_projects.empty:
        st.info(t("planning.no_projects_available", default="No projects available with the current filter."))
        return

    all_proj_ids = df_projects["id"].tolist()

    with top_sel_col:
        multi_header_label = f"🔍 {t('planning.select_multi_proj', default='Select Projects to Display in Multi-Gantt')} ({len(df_projects)} projects found)"
        selected_projects = st.multiselect(
            multi_header_label,
            options=all_proj_ids,
            default=all_proj_ids[:10] if len(all_proj_ids) > 10 else all_proj_ids,
            format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
            key="ms_multi_projects",
        )
        if not selected_projects:
            selected_projects = all_proj_ids

    selected_id = selected_projects[0]

    # Modal Dialog triggers (Project Tags & Task Tags from contextual menus)
    proj_modal_id = st.session_state.pop("modal_manage_project_tag", None)
    if proj_modal_id:
        _manage_project_tags_dialog(int(proj_modal_id), proj_map.get(proj_modal_id, f"Project #{proj_modal_id}"), tag_repo)

    task_modal_info = st.session_state.pop("modal_manage_task_tag", None)
    if task_modal_info and isinstance(task_modal_info, dict):
        _manage_task_tags_dialog(int(task_modal_info["task_id"]), str(task_modal_info["task_name"]), tag_repo)

    task_pool_modal_info = st.session_state.pop("modal_manage_task_pool", None)
    if task_pool_modal_info and isinstance(task_pool_modal_info, dict):
        _manage_task_resource_pools_dialog(
            task_id=int(task_pool_modal_info["task_id"]),
            task_name=str(task_pool_modal_info.get("task_name", f"Task #{task_pool_modal_info['task_id']}")),
            project_id=task_pool_modal_info.get("project_id", selected_id),
            pool_repo=pool_repo,
            milestone_repo=milestone_repo,
            org_repo=org_repo,
        )

    proj_pool_modal_id = st.session_state.pop("modal_manage_project_pool", None)
    if proj_pool_modal_id:
        _manage_project_resource_pools_dialog(
            int(proj_pool_modal_id),
            proj_map.get(int(proj_pool_modal_id), f"Project #{proj_pool_modal_id}"),
            pool_repo,
            milestone_repo,
            org_repo,
        )

    # Fetch all project bounds, project tags, and project pool assignments for constraint evaluation and tooltips
    proj_tags_map = tag_repo.get_project_tags_by_project_ids([int(p) for p in selected_projects if str(p).isdigit()])
    proj_pools_map = pool_repo.get_project_assignments_map([int(r["id"]) for _, r in df_projects.iterrows()])
    
    if len(selected_projects) == 1:
        s_id = int(selected_projects[0]) if str(selected_projects[0]).isdigit() else selected_projects[0]
        s_tags = proj_tags_map.get(s_id, [])
        if s_tags:
            tag_badges_html = "".join([
                f'<span style="background-color:#FDE8EC; color:#C41039; border:1px solid #C41039; padding:2px 8px; border-radius:10px; font-size:11.5px; font-weight:600; margin-right:5px; display:inline-block; margin-bottom:4px;">🏷️ {("[" + str(tg.get("tag_group_name")) + "] ") if tg.get("tag_group_name") else ""}{tg.get("tag_name") or tg.get("free_tag") or tg.get("tag")}</span>'
                for tg in s_tags
            ])
            st.markdown(f'<div style="margin-top:-6px; margin-bottom:6px;">{tag_badges_html}</div>', unsafe_allow_html=True)

    all_projects_list = [
        {
            "id": str(r["id"]),
            "name": f"{r['name']}",
            "tags": proj_tags_map.get(int(r["id"]), []),
            "pools": proj_pools_map.get(int(r["id"]), []),
        }
        for _, r in df_projects.iterrows()
    ]
    project_bounds = milestone_repo.get_all_project_date_bounds()

    # Gather tasks and dependencies for active project(s) via batch queries
    combined_steps_df = milestone_repo.get_milestones_for_projects(selected_projects)
    if not combined_steps_df.empty:
        # In multi-project view, display strictly the clean project name without ID prefix
        combined_steps_df["project_name"] = combined_steps_df["project_id"].apply(
            lambda pid: proj_map.get(pid, str(pid))
        )
    raw_dependencies = milestone_repo.get_dependencies_for_projects(selected_projects)

    if combined_steps_df.empty:
        st.info(t("planning.no_steps_defined"))
    else:
        steps_records = combined_steps_df.to_dict(orient="records")
        raw_tasks = [
            {
                "id": int(row["id"]),
                "task_name": str(row["task_name"]),
                "start_date": str(row["start_date"]),
                "end_date": str(row["end_date"]),
                "phase": str(row.get("phase", "General")),
                "progress_pct": int(row.get("progress_pct", 0)),
                "description": str(row.get("description", "")) if pd.notna(row.get("description")) else "",
                "project_id": str(row.get("project_id", selected_id)),
                "project_name": str(row.get("project_name", "")),
            }
            for row in steps_records
        ]

        evaluated_deps, task_violations = MilestoneService.evaluate_constraints(
            raw_tasks, raw_dependencies, project_bounds
        )

        # Batch load tags and resource pool assignments for all tasks
        all_task_ids = [int(row["id"]) for row in steps_records]
        task_tags_map = tag_repo.get_task_tags_by_task_ids(all_task_ids)
        task_pools_map = pool_repo.get_task_assignments_map(all_task_ids)

        # Precompute pool details for pools in task_pools_map
        all_task_pool_ids = {p["pool_id"] for plist in task_pools_map.values() for p in plist}
        pool_details_cache: dict[int, Any] = {
            pid: ResourcePoolService.calculate_pool_capacity(pid, org_repo, pool_repo, milestone_repo)
            for pid in all_task_pool_ids
        }

        # For each task, enrich pool objects with is_overassigned on that specific task and capacity
        enriched_task_pools_map: dict[int, list[dict[str, Any]]] = {}
        for tid, plist in task_pools_map.items():
            t_row = next((r for r in steps_records if int(r["id"]) == tid), None)
            t_start = str(t_row["start_date"]) if t_row else None
            t_end = str(t_row["end_date"]) if t_row else None
            enriched_list = []
            for p in plist:
                p_copy = dict(p)
                p_det = pool_details_cache.get(p["pool_id"])
                is_over = False
                if p_det:
                    p_copy["pool_capacity"] = p_det.total_capacity_fte
                    if float(p["fte"]) > (p_det.total_capacity_fte + 1e-4):
                        is_over = True
                    eff_s = str(p.get("start_date")) if pd.notna(p.get("start_date")) and str(p.get("start_date")).strip() else t_start
                    eff_e = str(p.get("end_date")) if pd.notna(p.get("end_date")) and str(p.get("end_date")).strip() else t_end
                    if not is_over and p_det.is_overassigned and eff_s and eff_e:
                        for ov in p_det.daily_overassignments:
                            if eff_s <= ov.date <= eff_e:
                                is_over = True
                                break
                p_copy["is_overassigned"] = is_over
                enriched_list.append(p_copy)
            enriched_task_pools_map[tid] = enriched_list

        # Index evaluated dependencies by task_id in O(N)
        deps_by_task_id: dict[int, list[dict[str, Any]]] = {}
        for d in evaluated_deps:
            t_id = d.get("task_id")
            if t_id is not None:
                deps_by_task_id.setdefault(int(t_id), []).append(d)

        # Build gantt tasks payload in fast O(N)
        gantt_tasks = []
        for row in steps_records:
            tid = int(row["id"])
            task_deps = deps_by_task_id.get(tid, [])
            first_pred = task_deps[0]["predecessor_task_id"] if task_deps and task_deps[0].get("predecessor_task_id") else None
            dep_str = str(int(first_pred)) if first_pred is not None else ""

            gantt_tasks.append({
                "id": str(tid),
                "name": str(row["task_name"]),
                "start": str(row["start_date"]),
                "end": str(row["end_date"]),
                "progress": int(row.get("progress_pct", 0)),
                "description": str(row.get("description", "")) if pd.notna(row.get("description")) else "",
                "dependencies": dep_str,
                "dependenciesList": task_deps,
                "violations": task_violations.get(tid, []),
                "tags": task_tags_map.get(tid, []),
                "pools": enriched_task_pools_map.get(tid, []),
                "phase": str(row.get("phase", "General")),
                "project_id": str(row["project_id"]),
                "project_name": str(row["project_name"]),
                "custom_class": "bar-milestone" if row["start_date"] == row["end_date"] else "bar-step",
            })

        # Quick Actions: Manage Project Pools & Task Pools without right-click
        qa_col1, qa_col2 = st.columns(2)
        with qa_col1:
            with st.expander(f"🏊 {t('planning.quick_project_pools', default='Quick Action: Assign Resource Pools to Project')}", expanded=False):
                quick_proj_choices = [
                    (int(r["id"]), f"{r['name']} (#{r['id']})")
                    for _, r in df_projects.iterrows()
                ]
                sel_quick_proj = st.selectbox(
                    t("planning.select_project_to_assign_pools", default="Select Project to Assign Pools"),
                    options=quick_proj_choices,
                    format_func=lambda x: x[1],
                    key="sb_quick_project_pool",
                )
                if st.button(t("planning.btn_open_project_pool_mgr", default="Open Project Pool Allocator"), key="btn_open_quick_proj_pool_mgr", type="primary"):
                    if sel_quick_proj:
                        st.session_state["modal_manage_project_pool"] = int(sel_quick_proj[0])
                        st.rerun()

        with qa_col2:
            with st.expander(f"🏊 {t('planning.quick_task_pools', default='Quick Action: Assign Resource Pools to Task')}", expanded=False):
                quick_task_choices = [
                    (int(r["id"]), f"{r['task_name']} (#{r['id']}) - {r.get('project_name', '')}")
                    for r in steps_records
                ]
                sel_quick_task = st.selectbox(
                    t("planning.select_task_to_assign_pools", default="Select Task to Assign Pools"),
                    options=quick_task_choices,
                    format_func=lambda x: x[1],
                    key="sb_quick_task_pool",
                )
                if st.button(t("planning.btn_open_pool_mgr", default="Open Task Pool Allocator"), key="btn_open_quick_pool_mgr", type="primary"):
                    if sel_quick_task:
                        target_tid = sel_quick_task[0]
                        target_rec = next((r for r in steps_records if int(r["id"]) == target_tid), None)
                        st.session_state["modal_manage_task_pool"] = {
                            "task_id": target_tid,
                            "task_name": target_rec["task_name"] if target_rec else f"Task #{target_tid}",
                            "project_id": target_rec["project_id"] if target_rec else selected_id,
                        }
                        st.rerun()

        # Render custom drag-and-drop component with multi-dependency metadata and i18n
        cur_loc = get_current_locale()
        gantt_translations = get_section_catalog("gantt", cur_loc)
        all_ext_tasks = milestone_repo.get_all_external_tasks_map()
        widget_key = f"gantt_{len(selected_projects)}_{selected_id}_{cur_loc}"
        gantt_event = _interactive_gantt(
            tasks=gantt_tasks,
            all_projects=all_projects_list,
            external_tasks=all_ext_tasks,
            project_id=selected_id,
            is_multi_project=True,
            translations=gantt_translations,
            key=widget_key,
        )

        # Handle bi-directional Drag & Drop changes from JS (deduplicated via nonce)
        if gantt_event and isinstance(gantt_event, dict):
            nonce = gantt_event.get("nonce")
            last_nonce = st.session_state.get("last_gantt_nonce")

            if nonce and nonce != last_nonce:
                st.session_state["last_gantt_nonce"] = nonce
                action = gantt_event.get("action")
                step_id = gantt_event.get("id")

                if action == "manage_project_tags":
                    p_id = gantt_event.get("project_id")
                    if p_id:
                        st.session_state["modal_manage_project_tag"] = int(p_id)
                        st.rerun()
                elif action == "manage_project_pools":
                    p_id = gantt_event.get("project_id")
                    if p_id:
                        st.session_state["modal_manage_project_pool"] = int(p_id)
                        st.rerun()
                elif action == "edit_project_details":
                    p_id = gantt_event.get("project_id")
                    if p_id:
                        st.session_state["nav_redirect"] = PAGE_PROJECT_MASTER
                        st.session_state["target_edit_project_id"] = int(p_id)
                        st.rerun()
                elif action == "manage_task_tags" and step_id:
                    st.session_state["modal_manage_task_tag"] = {
                        "task_id": int(step_id),
                        "task_name": str(gantt_event.get("task_name", "")),
                        "project_id": str(gantt_event.get("project_id", "")),
                    }
                    st.rerun()
                elif action == "manage_task_pools":
                    t_id = gantt_event.get("task_id") or step_id
                    if t_id:
                        st.session_state["modal_manage_task_pool"] = {
                            "task_id": int(t_id),
                            "task_name": str(gantt_event.get("task_name", "")),
                            "project_id": str(gantt_event.get("project_id", selected_id)),
                        }
                        st.rerun()
                elif action == "update_task_full" and step_id:
                    t_name = str(gantt_event.get("task_name", "")).strip()
                    t_phase = str(gantt_event.get("phase", "General")).strip()
                    t_start = str(gantt_event.get("start_date", "")).strip()
                    t_end = str(gantt_event.get("end_date", "")).strip()
                    t_prog = int(gantt_event.get("progress_pct", 0))
                    t_desc = str(gantt_event.get("description", "")).strip()
                    t_deps = gantt_event.get("dependencies")
                    if t_name and t_start and t_end:
                        milestone_repo.update_milestone(
                            milestone_id=int(step_id),
                            task_name=t_name,
                            phase=t_phase,
                            start_date=t_start,
                            end_date=t_end,
                            progress_pct=t_prog,
                            dependencies=t_deps,
                            description=t_desc,
                        )
                        st.toast(t("planning.toast_step_updated", name=t_name), icon="✏️")
                        st.rerun()
                elif action == "create_step_full":
                    t_proj = str(gantt_event.get("project_id", "")).strip() or selected_id
                    t_name = str(gantt_event.get("task_name", "")).strip()
                    t_phase = str(gantt_event.get("phase", "")).strip() or "General"
                    t_start = str(gantt_event.get("start_date", "")).strip()
                    t_end = str(gantt_event.get("end_date", "")).strip()
                    t_prog = int(gantt_event.get("progress_pct", 0))
                    t_desc = str(gantt_event.get("description", "")).strip()
                    t_deps = gantt_event.get("dependencies", [])

                    if t_name and t_start and t_end:
                        new_step_id = milestone_repo.create_milestone(
                            project_id=t_proj,
                            task_name=t_name,
                            phase=t_phase,
                            start_date=t_start,
                            end_date=t_end,
                            progress_pct=t_prog,
                            dependencies=t_deps,
                            description=t_desc,
                        )
                        st.toast(t("planning.toast_step_created", name=t_name, project_id=t_proj), icon="➕")
                        st.rerun()
                elif action == "update_dates" and step_id:
                    new_start = str(gantt_event.get("start_date", "")).strip()
                    new_end = str(gantt_event.get("end_date", "")).strip()
                    if new_start and new_end:
                        milestone_repo.update_dates(int(step_id), new_start, new_end)
                        st.toast(t("planning.toast_dates_updated", id=step_id, start=new_start, end=new_end), icon="📅")
                        st.rerun()
                elif action == "update_progress" and step_id:
                    new_prog = gantt_event.get("progress")
                    if new_prog is not None:
                        milestone_repo.update_progress(int(step_id), int(new_prog))
                        st.toast(t("planning.toast_progress_updated", id=step_id, progress=new_prog), icon="📊")
                        st.rerun()
                elif action == "delete_step" and step_id:
                    milestone_repo.delete_milestone(int(step_id))
                    st.toast(t("planning.toast_step_deleted", id=step_id), icon="🗑️")
                    st.rerun()

    # --------------------------------------------------------------------------
    # 2. CSV BULK STEP LOADER & EXPORTER
    # --------------------------------------------------------------------------
    st.divider()

    manage_project_id = st.selectbox(
        t("planning.csv_target_project", default="Select Target Project for CSV Bulk Loader"),
        options=df_projects["id"].tolist(),
        format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
        key="sb_manage_target_project",
    )

    df_steps = milestone_repo.get_milestones_by_project(manage_project_id)

    with st.expander(t("planning.csv_section_title"), expanded=False):
        st.subheader(f"{t('planning.csv_section_title')} ({manage_project_id})")
        col_exp, col_imp = st.columns(2)
        with col_exp:
            st.write(f"##### {t('planning.csv_export_title', default='Export Schedule Template')}")
            template_csv = MilestoneService.get_csv_template()
            st.download_button(
                label=t("planning.csv_download_template"),
                data=template_csv,
                file_name="steps_schedule_template.csv",
                mime="text/csv",
            )

        with col_imp:
            st.write(f"##### {t('planning.csv_import_title', default='Bulk Import Steps')}")
            uploaded_file = st.file_uploader(t("planning.csv_upload_label"), type=["csv"], key="uploader_steps")
            if uploaded_file is not None:
                try:
                    steps_payload = MilestoneService.parse_csv(uploaded_file, manage_project_id)
                    st.dataframe(pd.DataFrame(steps_payload).head(), width="stretch")
                    if st.button(t("planning.btn_import_csv")):
                        count = milestone_repo.bulk_create_milestones(steps_payload)
                        st.success(t("planning.csv_import_success", count=count, project_id=manage_project_id, default=f"Successfully imported {count} steps to {manage_project_id}!"))
                        st.rerun()
                except ValueError as val_err:
                    st.error(str(val_err))
                except Exception as e:
                    st.error(f"Error parsing CSV: {e}")
