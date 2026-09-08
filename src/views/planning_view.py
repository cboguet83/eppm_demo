"""Screen 4: Planning & Step Loader View (Interactive Drag & Drop Gantt and Plotly Roadmap)."""

import datetime
import html
import hashlib
import os
from typing import Any, Optional, Union

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from src.i18n import get_current_locale, get_section_catalog, t
from src.models.constants import PAGE_SETTINGS
from src.models.resource_pool import PoolAssignment
from src.models.tag import ProjectTag, TaskTag
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.resource_pool_repo import ResourcePoolRepository
from src.repositories.schema_repo import SchemaRepository
from src.repositories.tag_repo import TagRepository
from src.services.milestone_service import MilestoneService
from src.services.resource_pool_service import ResourcePoolService
from src.views.project_dialogs import open_edit_project_dialog
from src.repositories.portfolio_repo import portfolio_revision
from src.services.planning_data import (
    ensure_planning_indexes, load_planning_catalog, load_planning_steps,
    load_planning_project_metadata, load_planning_bounds, load_dependency_choices,
    load_project_summaries, affected_task_projects, build_task_payload,
)

# Declare Frappe Gantt Custom Component
_COMPONENT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "components",
    "gantt",
)
_interactive_gantt = components.declare_component("interactive_gantt", path=_COMPONENT_PATH)


def _get_gantt_event_nonce(gantt_event: dict[str, Any]) -> str:
    """Return the component nonce, with a deterministic fallback for older events."""
    nonce = gantt_event.get("nonce")
    if nonce:
        return str(nonce)
    return str(hash(frozenset(str(key) + str(value) for key, value in gantt_event.items())))


def _apply_immediate_gantt_update(
    gantt_event: dict[str, Any],
    milestone_repo: MilestoneRepository,
) -> bool:
    """Persist date/progress events before Streamlit starts its automatic rerun."""
    action = gantt_event.get("action")
    step_id = gantt_event.get("id")
    try:
        step_id_int = int(step_id)
    except (TypeError, ValueError):
        return False

    if action == "update_dates":
        new_start = str(gantt_event.get("start_date", "")).strip()
        new_end = str(gantt_event.get("end_date", "")).strip()
        try:
            start_date = datetime.date.fromisoformat(new_start)
            end_date = datetime.date.fromisoformat(new_end)
        except ValueError:
            return False
        if end_date < start_date:
            return False

        updated = milestone_repo.update_dates(step_id_int, new_start, new_end)
        if updated:
            st.toast(
                t(
                    "planning.toast_dates_updated",
                    id=step_id_int,
                    start=new_start,
                    end=new_end,
                ),
                icon="📅",
            )
        return updated

    if action == "update_progress":
        try:
            new_progress = int(gantt_event.get("progress"))
        except (TypeError, ValueError):
            return False

        updated = milestone_repo.update_progress(step_id_int, new_progress)
        if updated:
            st.toast(
                t(
                    "planning.toast_progress_updated",
                    id=step_id_int,
                    progress=new_progress,
                ),
                icon="📊",
            )
        return updated

    return False


def _handle_gantt_component_change(
    widget_key: str,
    milestone_repo: MilestoneRepository,
) -> None:
    """Handle inline Gantt mutations in the component callback.

    Component callbacks run before Streamlit executes the automatic rerun, so
    the rebuilt Gantt immediately reads the newly persisted task values.
    """
    gantt_event = st.session_state.get(widget_key)
    if not isinstance(gantt_event, dict):
        return
    if gantt_event.get("action") not in {
        "filter_project",
        "update_dates",
        "update_progress",
        "load_dependency_tasks",
        "load_project_tasks",
        "initialize_planning",
    }:
        return

    nonce = _get_gantt_event_nonce(gantt_event)
    if nonce == st.session_state.get("last_gantt_nonce"):
        return

    # Consume the event even when its client-supplied payload is invalid. This
    # prevents it from falling through to the post-render event handler.
    st.session_state["last_gantt_nonce"] = nonce
    if gantt_event.get("action") == "initialize_planning":
        st.session_state.pop('planning_chart_snapshot', None)
    elif gantt_event.get("action") == "load_project_tasks":
        st.session_state['planning_pending_change'] = dict(gantt_event)
    elif gantt_event.get("action") == "load_dependency_tasks":
        try:
            project_id = int(gantt_event.get("project_id"))
        except (TypeError, ValueError):
            return
        st.session_state['planning_dependency_response'] = {
            'project_id': str(project_id), 'nonce': nonce,
            'tasks': load_dependency_choices(milestone_repo.db_path, portfolio_revision(milestone_repo.db_path), project_id),
        }
    elif gantt_event.get("action") == "filter_project":
        _focus_planning_on_project(gantt_event)
        st.session_state['planning_needs_full_rerun'] = True
    else:
        before = portfolio_revision(milestone_repo.db_path)
        if _apply_immediate_gantt_update(gantt_event, milestone_repo):
            st.session_state['planning_pending_change'] = {**gantt_event, 'before_revision': before}


def _normalise_planning_filter_values(value: Any) -> list[str]:
    """Convert scalar and multi-valued project attributes to filter values."""
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    return [str(value).strip()]


def _unique_planning_filter_options(series: pd.Series) -> list[str]:
    """Return the sorted distinct values available for one filter field."""
    values = {
        item
        for value in series.tolist()
        for item in _normalise_planning_filter_values(value)
        if item
    }
    return sorted(values, key=str.casefold)


def _apply_planning_flex_filters(
    frame: pd.DataFrame,
    filters: dict[str, list[str]],
    match_all_values: bool = False,
) -> pd.DataFrame:
    """Apply AND across fields and Any/All matching within each field."""
    filtered = frame.copy()
    for column, selected_values in filters.items():
        if column not in filtered.columns or not selected_values:
            continue
        wanted = {str(value).casefold() for value in selected_values}

        def cell_matches(value: Any) -> bool:
            actual = {
                item.casefold()
                for item in _normalise_planning_filter_values(value)
            }
            return wanted.issubset(actual) if match_all_values else bool(wanted & actual)

        filtered = filtered[filtered[column].apply(cell_matches)]
    return filtered


def _clear_planning_flex_filter_state(*, clear_tracking: bool = False) -> None:
    """Clear only state owned by the planning flexible filter."""
    for key in list(st.session_state):
        if str(key).startswith("planning_flex_"):
            del st.session_state[key]
    if clear_tracking:
        st.session_state.pop("planning_last_flex_signature", None)


def _focus_planning_on_project(gantt_event: dict[str, Any]) -> bool:
    """Clear competing filters and focus the planning page on one project."""
    try:
        project_id = int(gantt_event.get("project_id"))
    except (TypeError, ValueError):
        return False
    if project_id <= 0:
        return False

    _clear_planning_flex_filter_state(clear_tracking=True)
    st.session_state.pop("active_resource_pool_filter", None)
    st.session_state.pop("pending_resource_pool_filter", None)
    st.session_state.pop("pending_clear_resource_pool_filter", None)
    st.session_state["ms_planning_tag_filter"] = []
    st.session_state["last_planning_tag_filter"] = []
    st.session_state["ms_multi_projects"] = [project_id]

    project_name = str(gantt_event.get("project_name", "")).strip()
    label = project_name or f"Project #{project_id}"
    st.toast(f"Filtered planning to {label}", icon="🔍")
    return True


def _build_resource_pool_hierarchy(
    pool_repo: ResourcePoolRepository,
    pools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a loop-safe tree of pool groups and ungrouped pools for the Gantt."""
    pool_by_id = {int(pool["id"]): pool for pool in pools}
    groups = pool_repo.get_all_pool_groups()
    if groups.empty:
        return [
            {
                "key": f"pool:{pool_id}",
                "node_type": "pool",
                "pool_id": pool_id,
                "name": str(pool["name"]),
            }
            for pool_id, pool in sorted(
                pool_by_id.items(), key=lambda item: str(item[1]["name"]).casefold()
            )
        ]

    group_by_id = {
        int(row["id"]): {
            "name": str(row["name"]),
            "description": (
                str(row.get("description")) if pd.notna(row.get("description")) else ""
            ),
        }
        for _, row in groups.iterrows()
    }
    members_by_group: dict[int, tuple[list[int], list[int]]] = {}
    child_group_ids: set[int] = set()
    grouped_pool_ids: set[int] = set()
    for row in pool_repo.get_all_group_members().to_dict("records"):
        pool_ids, child_ids = members_by_group.setdefault(int(row["group_id"]), ([], []))
        if pd.notna(row["pool_id"]):
            pool_ids.append(int(row["pool_id"]))
            grouped_pool_ids.add(int(row["pool_id"]))
        if pd.notna(row["child_group_id"]):
            child_ids.append(int(row["child_group_id"]))
            child_group_ids.add(int(row["child_group_id"]))

    def pool_node(pool_id: int, path: tuple[int, ...]) -> Optional[dict[str, Any]]:
        pool = pool_by_id.get(pool_id)
        if pool is None:
            return None
        path_key = "/".join(str(item) for item in path)
        return {
            "key": f"pool:{path_key}:{pool_id}" if path_key else f"pool:{pool_id}",
            "node_type": "pool",
            "pool_id": pool_id,
            "name": str(pool["name"]),
        }

    def group_node(group_id: int, path: tuple[int, ...]) -> dict[str, Any]:
        group = group_by_id[group_id]
        current_path = (*path, group_id)
        path_key = "/".join(str(item) for item in current_path)
        if group_id in path:
            return {
                "key": f"group:{path_key}:cycle",
                "node_type": "group",
                "group_id": group_id,
                "name": group["name"],
                "children": [],
                "descendant_pool_ids": [],
                "cycle_blocked": True,
            }

        direct_pool_ids, direct_child_ids = members_by_group.get(group_id, ([], []))
        children: list[dict[str, Any]] = []
        for child_id in sorted(
            direct_child_ids,
            key=lambda item: group_by_id.get(item, {}).get("name", "").casefold(),
        ):
            if child_id in group_by_id:
                children.append(group_node(child_id, current_path))
        for pool_id in sorted(
            direct_pool_ids,
            key=lambda item: str(pool_by_id.get(item, {}).get("name", "")).casefold(),
        ):
            node = pool_node(pool_id, current_path)
            if node is not None:
                children.append(node)
        return {
            "key": f"group:{path_key}",
            "node_type": "group",
            "group_id": group_id,
            "name": group["name"],
            "description": group["description"],
            "children": children,
            "descendant_pool_ids": sorted({
                pid for child in children
                for pid in ([child["pool_id"]] if child["node_type"] == "pool" else child["descendant_pool_ids"])
            }),
        }

    root_group_ids = sorted(
        set(group_by_id) - child_group_ids,
        key=lambda item: group_by_id[item]["name"].casefold(),
    )
    if not root_group_ids:
        root_group_ids = sorted(group_by_id, key=lambda item: group_by_id[item]["name"].casefold())

    hierarchy = [group_node(group_id, ()) for group_id in root_group_ids]
    for pool_id in sorted(
        set(pool_by_id) - grouped_pool_ids,
        key=lambda item: str(pool_by_id[item]["name"]).casefold(),
    ):
        node = pool_node(pool_id, ())
        if node is not None:
            hierarchy.append(node)
    return hierarchy


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
            p_status = ResourcePoolService.calculate_project_pool_status(project_id, p_id, org_repo, pool_repo, milestone_repo)
            minimum_capacity = float(p_status["minimum_capacity_fte"])

            if p_status["is_overassigned"]:
                status_html = f'<span style="background-color:#FDE8EC; color:#C41039; border:1px solid #C41039; padding:2px 7px; border-radius:10px; font-weight:700; font-size:11px;">⚠️ Overassigned (Peak: {p_status["project_peak_assigned_fte"]:.2f} / Min. effective cap: {minimum_capacity:.2f} FTE)</span>'
            else:
                status_html = f'<span style="background-color:#ECFDF5; color:#047857; border:1px solid #10B981; padding:2px 7px; border-radius:10px; font-weight:700; font-size:11px;">✅ OK (Peak: {p_status["project_peak_assigned_fte"]:.2f} / Min. effective cap: {minimum_capacity:.2f} FTE)</span>'

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


def _handle_filter_by_resource_pool(
    gantt_event: dict[str, Any],
    pool_details_cache: dict[int, Any],
    org_repo: OrganizationRepository,
    pool_repo: ResourcePoolRepository,
    milestone_repo: MilestoneRepository,
    selected_projects: list[Any],
    all_proj_ids: list[int],
    master_proj_ids: Optional[list[int]] = None,
) -> None:
    """Handles resource pool context menu filter event.

    Queues session state modifications via pending state keys to avoid StreamlitAPIException
    from modifying widget state after widget instantiation.

    Args:
        gantt_event: Event dictionary from Gantt component.
        pool_details_cache: Cache of pool details.
        org_repo: Organization repository.
        pool_repo: Resource pool repository.
        milestone_repo: Milestone repository.
        selected_projects: Currently selected project IDs.
        all_proj_ids: All available project IDs under current filter.
        master_proj_ids: Complete list of all project IDs in the database.
    """
    pool_id = int(gantt_event.get("pool_id", 0))
    start_date = str(gantt_event.get("start_date", "")).strip()[:10]
    end_date = str(gantt_event.get("end_date", "")).strip()[:10]
    clear_other = bool(gantt_event.get("clear_other_filters", True))
    pool_name = str(gantt_event.get("pool_name", ""))

    p_cap = pool_details_cache.get(pool_id)
    if not p_cap:
        p_cap = ResourcePoolService.calculate_pool_capacity(
            pool_id, org_repo, pool_repo, milestone_repo
        )
    matching_pids = ResourcePoolService.get_projects_consuming_pool_in_period(
        p_cap.assignments, start_date, end_date
    )
    ref_proj_ids = master_proj_ids if (clear_other and master_proj_ids) else all_proj_ids

    if clear_other:
        target_pids = matching_pids
    else:
        current_pids = [int(p) for p in selected_projects if str(p).isdigit()]
        intersected = [p for p in current_pids if p in matching_pids]
        target_pids = intersected if intersected else matching_pids

    valid_target_pids = [p for p in target_pids if p in ref_proj_ids]

    st.session_state["active_resource_pool_filter"] = {
        "pool_id": pool_id,
        "pool_name": pool_name or p_cap.pool_name,
        "start_date": start_date,
        "end_date": end_date,
        "clear_other_filters": clear_other,
        "project_ids": valid_target_pids,
        "count": len(valid_target_pids),
    }

    # Queue state updates to be applied before widgets are instantiated on rerun
    st.session_state["pending_resource_pool_filter"] = {
        "clear_other": clear_other,
        "target_pids": valid_target_pids,
    }

    if valid_target_pids:
        st.toast(f"Filtered to {len(valid_target_pids)} projects consuming {pool_name}", icon="🔍")
    else:
        st.toast(f"No projects consuming {pool_name} in {start_date} → {end_date}", icon="⚠️")
    st.rerun()


def _handle_clear_resource_pool_filter(all_proj_ids: Optional[list[int]] = None) -> None:
    """Clears the active resource pool filter and resets project selection.

    Args:
        all_proj_ids: Optional list of all project IDs.
    """
    st.session_state.pop("active_resource_pool_filter", None)
    st.session_state["pending_clear_resource_pool_filter"] = True
    st.toast("Resource pool filter cleared", icon="✖")
    st.rerun()


def _render_filtered_active_allocations(
    active_rf: dict[str, Any],
    pool_details_cache: dict[int, Any],
    org_repo: OrganizationRepository,
    pool_repo: ResourcePoolRepository,
    milestone_repo: MilestoneRepository,
) -> None:
    """Renders the Active Allocations on Projects & Tasks table below the resource pools table.

    Displays active allocations overlapping the filtered period, differentiating
    project-level and task-level assignments, without the action column.

    Args:
        active_rf: Active resource pool filter dictionary from session state.
        pool_details_cache: Cache mapping pool IDs to PoolCapacityDetail instances.
        org_repo: Organization repository instance.
        pool_repo: Resource pool repository instance.
        milestone_repo: Milestone repository instance.
    """
    f_pool_id = int(active_rf.get("pool_id", 0))
    f_pool_name = str(active_rf.get("pool_name", "Pool"))
    f_start = str(active_rf.get("start_date", ""))[:10]
    f_end = str(active_rf.get("end_date", ""))[:10]

    p_cap = pool_details_cache.get(f_pool_id)
    if not p_cap:
        p_cap = ResourcePoolService.calculate_pool_capacity(
            f_pool_id, org_repo, pool_repo, milestone_repo
        )

    # Filter assignments active during the filtered period
    pool_active_assignments: list[dict[str, Any]] = []
    for a in p_cap.assignments:
        a_start = str(a.get("start_date", ""))[:10]
        a_end = str(a.get("end_date", ""))[:10]
        fte_val = float(a.get("fte_assigned", 0.0))
        if fte_val > 0 and a_start <= f_end and a_end >= f_start:
            pool_active_assignments.append(dict(a, pool_name=f_pool_name))

    st.markdown("---")
    st.write(
        f"#### 📁 / 📋 {t('settings.assignments_section_title', default='Active Allocations on Projects & Tasks')} "
        f"— <span style='color:#2563EB;'>{html.escape(f_pool_name)}</span>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"Showing active resource assignments overlapping `{f_start} → {f_end}`. "
        "Project-level allocations apply across the whole project, whereas task-level allocations apply to specific steps."
    )

    if not pool_active_assignments:
        st.info(f"No active allocations found for {f_pool_name} in `{f_start} → {f_end}`.")
        return

    table_rows: list[str] = []
    total_active_fte = 0.0

    for a in pool_active_assignments:
        p_id = a["project_id"]
        p_name = html.escape(str(a.get("project_name", f"Project #{p_id}")))
        t_id = a.get("task_id")
        t_name = html.escape(str(a.get("task_name", "—")))
        fte = float(a.get("fte_assigned", 0.0))
        total_active_fte += fte
        s_date = a.get("start_date", "")
        e_date = a.get("end_date", "")
        is_custom = bool(a.get("is_custom_period", False))
        notes = html.escape(str(a.get("notes", "")))
        pool_badge_name = html.escape(str(a.get("pool_name", f_pool_name)))

        proj_badge = (
            f'<span style="color:#0369A1; font-weight:700;">'
            f'📁 {p_name} [#{p_id}]</span>'
        )

        if t_id:
            task_badge = (
                f'<span style="color:#2563EB; font-weight:600;">'
                f'📋 {t_name} [#{t_id}]</span>'
            )
        else:
            task_badge = (
                f'<span style="color:#64748B; font-style:italic; background:#F1F5F9; '
                f'padding:2px 7px; border-radius:3px; border:1px dashed #CBD5E1;">'
                f'— Project Level</span>'
            )

        period_badge = (
            f'<span style="font-size:12px; color:#334155;">{s_date} → {e_date}</span> '
            f'<span style="font-size:10px; background:#E2E8F0; color:#475569; padding:1px 5px; border-radius:3px;">'
            f'{"Custom" if is_custom else "Full Project"}</span>'
        )

        pool_badge = (
            f'<span style="background:#EFF6FF; color:#1D4ED8; font-weight:600; '
            f'padding:2px 8px; border-radius:4px; border:1px solid #BFDBFE;">'
            f'🏊 {pool_badge_name}</span>'
        )

        table_rows.append(
            f'<tr style="border-bottom:1px solid #E2E8F0;">'
            f'<td style="padding:8px 10px; font-weight:600; color:#475569;">#{a["id"]}</td>'
            f'<td style="padding:8px 10px;">{pool_badge}</td>'
            f'<td style="padding:8px 10px;">{proj_badge}</td>'
            f'<td style="padding:8px 10px;">{task_badge}</td>'
            f'<td style="padding:8px 10px;"><span style="font-weight:700; color:#0F172A; background:#F1F5F9; padding:2px 7px; border-radius:4px;">{fte:.2f} FTE</span></td>'
            f'<td style="padding:8px 10px;">{period_badge}</td>'
            f'<td style="padding:8px 10px; color:#64748B; font-size:12px;">{notes or "—"}</td>'
            f'</tr>'
        )

    header_html = (
        f'<tr style="background:#F8FAFC; border-bottom:2px solid #CBD5E1; color:#475569; font-weight:700; font-size:12px; text-transform:uppercase;">'
        f'<th style="padding:8px 10px; text-align:left;">ID</th>'
        f'<th style="padding:8px 10px; text-align:left;">{t("settings.col_pool", default="Resource Pool")}</th>'
        f'<th style="padding:8px 10px; text-align:left;">{t("settings.col_project", default="Project")}</th>'
        f'<th style="padding:8px 10px; text-align:left;">{t("settings.col_task", default="Task / Step")}</th>'
        f'<th style="padding:8px 10px; text-align:left;">{t("master_data.field_fte", default="Assigned FTE")}</th>'
        f'<th style="padding:8px 10px; text-align:left;">{t("master_data.field_period", default="Effective Period")}</th>'
        f'<th style="padding:8px 10px; text-align:left;">{t("master_data.field_notes", default="Notes")}</th>'
        f'</tr>'
    )

    footer_html = (
        f'<tr style="background:#F1F5F9; font-weight:700; border-top:2px solid #CBD5E1; color:#0F172A;">'
        f'<td colspan="4" style="padding:8px 10px; text-align:right;">Total Active Allocation:</td>'
        f'<td style="padding:8px 10px;"><span style="background:#2563EB; color:#FFFFFF; padding:2px 8px; border-radius:4px; font-weight:700;">{total_active_fte:.2f} FTE</span></td>'
        f'<td colspan="2" style="padding:8px 10px; color:#64748B; font-size:11.5px; font-weight:400;">Filtered Period: {f_start} → {f_end}</td>'
        f'</tr>'
    )

    full_table_html = (
        f'<div style="overflow-x:auto; border:1px solid #E2E8F0; border-radius:6px; margin-bottom:12px;">'
        f'<table style="width:100%; border-collapse:collapse; font-size:12.5px; text-align:left; background:#FFFFFF;">'
        f'<thead>{header_html}</thead>'
        f'<tbody>{"".join(table_rows)}</tbody>'
        f'<tfoot>{footer_html}</tfoot>'
        f'</table>'
        f'</div>'
    )

    st.markdown(full_table_html, unsafe_allow_html=True)


@st.cache_data(ttl=60, max_entries=8, show_spinner=False, hash_funcs={tuple: repr})
def _load_planning_pool_payload(db_path, revision, project_ids, _pool_details_cache, pool_ids=None):
    """Reuse exact selected-scope daily demand until source data or scope changes."""
    selected_projects = project_ids
    pool_details_cache = _pool_details_cache
    pool_repo = ResourcePoolRepository(db_path)
    org_repo = OrganizationRepository(db_path)
    milestone_repo = MilestoneRepository(db_path)
    # Build resource pools payload for the demand & capacity grid below the Gantt
    scope_pids = [int(p) for p in selected_projects if str(p).isdigit()]
    scope_pid_set = set(scope_pids)
    df_all_pools = pool_repo.get_all_pools()
    if pool_ids is not None:
        df_all_pools = df_all_pools[df_all_pools.id.isin(pool_ids)]
    resource_pools_payload: list[dict[str, Any]] = []
    if not df_all_pools.empty:
        for _, p_row in df_all_pools.iterrows():
            p_id = int(p_row["id"])
            p_name = str(p_row["name"])
            if p_id not in pool_details_cache:
                pool_details_cache[p_id] = ResourcePoolService.calculate_pool_capacity(
                    p_id, org_repo, pool_repo, milestone_repo
                )
            p_cap = pool_details_cache[p_id]
            effective_daily_capacity = (
                p_cap.daily_assigned_capacity
                if p_cap.has_assigned_resources
                else {}
            )
            # The usual portfolio-wide view is already computed in the pool
            # cache. Recalculate only when the filter excludes an assignment.
            if all(int(a["project_id"]) in scope_pid_set for a in p_cap.assignments):
                scope_usage = p_cap.daily_usage
                scope_overassignments = p_cap.daily_overassignments
            else:
                scope_usage = ResourcePoolService.calculate_pool_scope_daily_usage(
                    p_cap.assignments, scope_pids
                )
                scope_overassignments = ResourcePoolService.calculate_daily_overassignments(
                    scope_usage,
                    p_cap.effective_capacity_fte,
                    effective_daily_capacity,
                )
            resource_pools_payload.append({
                "id": p_id,
                "name": p_name,
                "capacity": float(p_cap.total_capacity_fte),
                "theoretical_capacity": (
                    float(p_cap.defined_capacity_fte)
                    if p_cap.defined_capacity_fte is not None
                    else float(p_cap.total_capacity_fte)
                ),
                "assigned_capacity": float(p_cap.assigned_capacity_fte),
                "displayed_assigned_capacity": float(p_cap.effective_capacity_fte),
                "has_assigned_resources": bool(p_cap.has_assigned_resources),
                "daily_assigned_capacity": effective_daily_capacity,
                "peak_demand": float(p_cap.peak_assigned_fte),
                "is_overassigned": bool(p_cap.is_overassigned),
                "daily_usage": p_cap.daily_usage,
                "overallocated_dates": [
                    item.date for item in p_cap.daily_overassignments
                ],
                "selected_projects_daily_usage": scope_usage,
                "selected_projects_overallocated_dates": [
                    item.date for item in scope_overassignments
                ],
                "assignments": [
                    {
                        "project_id": int(a["project_id"]),
                        "start_date": str(a.get("start_date", "")),
                        "end_date": str(a.get("end_date", "")),
                    }
                    for a in p_cap.assignments
                ],
            })

    resource_pool_hierarchy = [] if pool_ids is not None else _build_resource_pool_hierarchy(
        pool_repo,
        resource_pools_payload,
    )
    return resource_pools_payload, resource_pool_hierarchy


@st.fragment
def _render_planning_chart(project_repo, milestone_repo, tag_repo, pool_repo, org_repo,
                           selected_projects, df_projects, proj_map, master_proj_ids, scope_signature):
    from uuid import uuid4
    from src.services.pool_capacity_cache import load_pool_capacities
    from src.services.planning_transport import pack_pool_payloads
    if st.session_state.pop('planning_needs_full_rerun', False):
        st.rerun()
    db_path = project_repo.db_path
    selected_id = selected_projects[0]
    all_proj_ids = df_projects.id.tolist()
    ids = tuple(sorted(map(int, selected_projects)))
    scope = (ids, get_current_locale(), repr(scope_signature))
    widget_key = 'planning_lazy_gantt'
    snapshot = st.session_state.get('planning_chart_snapshot')
    event = st.session_state.pop('planning_pending_change', None)
    revision = portfolio_revision(db_path)
    unchanged_scope = snapshot is not None and snapshot['scope'] == scope
    known_edit = (event and event.get('before_revision') and unchanged_scope
                  and event['before_revision'] == snapshot['revision'])
    rebuild = not unchanged_scope or (revision != snapshot['revision'] and not known_edit)
    if rebuild:
        details = {d.pool_id: d for d in load_pool_capacities(db_path, details=True)}
        summaries = load_project_summaries(db_path, revision, ids)
        pools, hierarchy = _load_planning_pool_payload(db_path, revision, ids, details)
        bounds = {str(p['id']): (p['start'], p['end']) for p in summaries}
        loaded = list(ids) if len(ids) == 1 else []
        tasks = build_task_payload(db_path, loaded, bounds, details) if loaded else []
        snapshot = {'scope': scope, 'token': uuid4().hex, 'details': details, 'bounds': bounds,
                    'loaded': loaded, 'revision': portfolio_revision(db_path)}
        st.session_state['planning_chart_snapshot'] = snapshot
        args = dict(tasks=tasks, project_summaries=summaries, lazy_projects=True,
                    loaded_project_ids=loaded, scope_token=snapshot['token'],
                    all_projects=[{'id': str(r.id), 'name': r.name} for r in df_projects.itertuples()],
                    external_tasks={}, project_id=selected_id, is_multi_project=True,
                    translations=get_section_catalog('gantt', get_current_locale()),
                    resource_pools=pack_pool_payloads(pools), resource_pool_hierarchy=hierarchy,
                    active_resource_filter=st.session_state.get('active_resource_pool_filter'),
                    data_revision=snapshot['token'])
    else:
        args = {}
        patch = None
        if event and event.get('action') == 'load_project_tasks' and event.get('scope_token') == snapshot['token']:
            requested = []
            for value in event.get('project_ids', [])[:25]:
                try:
                    pid = int(value)
                except (ValueError, TypeError):
                    continue
                if pid in ids and pid not in requested:
                    requested.append(pid)
            patch = {'replace_projects': requested, 'tasks': build_task_payload(db_path, requested, snapshot['bounds'], snapshot['details'])}
            loaded = [p for p in snapshot['loaded'] if p not in requested] + requested
            evicted, snapshot['loaded'] = loaded[:-100], loaded[-100:]
            patch['evict_project_ids'] = evicted
        elif known_edit:
            changed, pool_ids = affected_task_projects(db_path, int(event['id']))
            for pid in changed:
                snapshot['bounds'][pid] = snapshot['bounds'][str(pid)] = milestone_repo.get_project_date_bounds(pid)
            if event['action'] == 'update_progress':
                pool_ids = set()
            if pool_ids:
                snapshot['details'].update({d.pool_id: d for d in load_pool_capacities(db_path, details=True, pool_ids=pool_ids)})
            refresh = changed.intersection(snapshot['loaded'])
            patch = {'replace_projects': sorted(refresh),
                     'tasks': build_task_payload(db_path, refresh, snapshot['bounds'], snapshot['details']),
                     'project_summaries': load_project_summaries(db_path, portfolio_revision(db_path), tuple(sorted(changed.intersection(ids))))}
            if pool_ids:
                patch['resource_pools'], _ = _load_planning_pool_payload(db_path, portfolio_revision(db_path), ids,
                                                                        snapshot['details'], tuple(sorted(pool_ids)))
                patch['resource_pools'] = pack_pool_payloads(patch['resource_pools'])
            snapshot['revision'] = portfolio_revision(db_path)
        if patch is not None:
            metadata_ids = patch['replace_projects']
            tags, pools = load_planning_project_metadata(db_path, portfolio_revision(db_path), tuple(metadata_ids))
            patch['project_metadata'] = [{'id': str(pid), 'tags': tags.get(pid, []), 'pools': pools.get(pid, [])} for pid in metadata_ids]
            patch.update(scope_token=snapshot['token'], nonce=event.get('nonce'), loaded_project_ids=snapshot['loaded'])
            args['patch'] = patch
    response = st.session_state.pop('planning_dependency_response', None)
    if response:
        args['dependency_response'] = response
    pool_details_cache = snapshot['details']
    gantt_event = _interactive_gantt(**args, key=widget_key,
        on_change=lambda: _handle_gantt_component_change(widget_key, milestone_repo))

    # Handle bi-directional Drag & Drop changes from JS (deduplicated via nonce)
    if gantt_event and isinstance(gantt_event, dict):
        nonce = _get_gantt_event_nonce(gantt_event)
        last_nonce = st.session_state.get("last_gantt_nonce")

        if nonce and nonce != last_nonce:
            st.session_state["last_gantt_nonce"] = nonce
            action = gantt_event.get("action")
            step_id = gantt_event.get("id")

            if action == "filter_by_resource_pool":
                _handle_filter_by_resource_pool(
                    gantt_event=gantt_event,
                    pool_details_cache=pool_details_cache,
                    org_repo=org_repo,
                    pool_repo=pool_repo,
                    milestone_repo=milestone_repo,
                    selected_projects=selected_projects,
                    all_proj_ids=all_proj_ids,
                    master_proj_ids=master_proj_ids,
                )
            elif action == "clear_resource_pool_filter":
                _handle_clear_resource_pool_filter(master_proj_ids)
            elif action == "go_to_pool_details":
                pool_id = gantt_event.get("pool_id")
                if pool_id:
                    st.session_state["settings_active_section"] = "organization"
                    st.session_state["rb_settings_section"] = "org_structure"
                    st.session_state["settings_active_tab"] = "resource_pools"
                    st.session_state["target_resource_pool_id"] = int(pool_id)
                    st.session_state["nav_redirect"] = PAGE_SETTINGS
                    st.rerun()
            elif action == "manage_project_tags":
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
                    st.session_state["modal_edit_project"] = int(p_id)
                    st.rerun()
            elif action == "filter_project":
                # The callback normally applies this before the automatic
                # component rerun. Queue a compatibility fallback only.
                st.session_state["pending_project_context_filter"] = gantt_event
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
                # Normally handled by ``on_change`` before this render. This
                # fallback preserves compatibility without starting a second rerun.
                _apply_immediate_gantt_update(gantt_event, milestone_repo)
            elif action == "update_progress" and step_id:
                _apply_immediate_gantt_update(gantt_event, milestone_repo)
            elif action == "delete_step" and step_id:
                milestone_repo.delete_milestone(int(step_id))
                st.toast(t("planning.toast_step_deleted", id=step_id), icon="🗑️")
                st.rerun()

    # --------------------------------------------------------------------------
    # ACTIVE ALLOCATIONS ON PROJECTS & TASKS (Shown when a Resource Pool filter is active)
    # --------------------------------------------------------------------------
    active_rf = st.session_state.get("active_resource_pool_filter")
    if active_rf and pool_repo is not None:
        _render_filtered_active_allocations(
            active_rf=active_rf,
            pool_details_cache=pool_details_cache,
            org_repo=org_repo,
            pool_repo=pool_repo,
            milestone_repo=milestone_repo,
        )


@st.fragment
def render_planning_milestones(
    project_repo: ProjectRepository,
    milestone_repo: MilestoneRepository,
    tag_repo: Optional[TagRepository] = None,
    pool_repo: Optional[ResourcePoolRepository] = None,
    org_repo: Optional[OrganizationRepository] = None,
    schema_repo: Optional[SchemaRepository] = None,
) -> None:
    """Renders the Planning & Step Loader screen with interactive drag & drop and Plotly timeline."""
    if tag_repo is None:
        tag_repo = TagRepository(project_repo.db_path)
    if pool_repo is None:
        pool_repo = ResourcePoolRepository(project_repo.db_path)
    if org_repo is None:
        org_repo = OrganizationRepository(project_repo.db_path)
    if schema_repo is None:
        schema_repo = SchemaRepository(project_repo.db_path)

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

    ensure_planning_indexes(project_repo.db_path)
    revision = portfolio_revision(project_repo.db_path)
    params = schema_repo.get_all_parameters()
    chosen_fields = set(st.session_state.get('planning_flex_fields', []))
    property_ids = tuple(sorted(str(p['param_id']) for p in params.to_dict('records')
        if p['param_name'] in chosen_fields or f"{p['param_name']} ({p['param_id']})" in chosen_fields))
    df_projects, project_filter_frame, params, project_tag_records = load_planning_catalog(
        project_repo.db_path, revision, property_ids)

    if df_projects.empty:
        st.info(t("master_data.dynamic_empty", default="No projects registered yet."))
        return

    master_proj_ids = [int(p) for p in df_projects["id"].tolist()]
    proj_map = dict(zip(df_projects["id"], df_projects["name"]))

    # --------------------------------------------------------------------------
    # TOP CONTROL: Flexible filters, project tags, and project multi-selector
    # --------------------------------------------------------------------------
    df_all_proj_tags = pd.DataFrame(project_tag_records)
    available_tags_set: set[str] = set()
    project_tags_by_id: dict[int, list[str]] = {}
    if not df_all_proj_tags.empty:
        for r in project_tag_records:
            t_name = r.get("tag_name")
            f_name = r.get("free_tag")
            if pd.notna(t_name) and str(t_name).strip():
                tag_name = str(t_name).strip()
                available_tags_set.add(tag_name)
                project_tags_by_id.setdefault(int(r["project_id"]), []).append(tag_name)
            if pd.notna(f_name) and str(f_name).strip():
                free_tag = str(f_name).strip()
                available_tags_set.add(free_tag)
                project_tags_by_id.setdefault(int(r["project_id"]), []).append(free_tag)

    available_tags_list = sorted(list(available_tags_set))

    # 1. Check for external navigation focus (e.g. from Resource Pools table jump)
    target_pid = st.session_state.pop("target_planning_project_id", None)
    if target_pid is not None:
        try:
            target_pid_int = int(target_pid)
            _clear_planning_flex_filter_state(clear_tracking=True)
            st.session_state["ms_planning_tag_filter"] = []
            st.session_state["ms_multi_projects"] = [target_pid_int]
        except (ValueError, TypeError):
            pass

    # 2. Check for pending resource pool filter clears (must be applied BEFORE widgets instantiate)
    if st.session_state.pop("pending_clear_resource_pool_filter", False):
        st.session_state.pop("active_resource_pool_filter", None)
        _clear_planning_flex_filter_state(clear_tracking=True)
        st.session_state["ms_planning_tag_filter"] = []
        st.session_state["last_planning_tag_filter"] = []
        st.session_state["ms_multi_projects"] = master_proj_ids

    # 3. Check for pending resource pool filter updates (must be applied BEFORE widgets instantiate)
    pending_rf = st.session_state.pop("pending_resource_pool_filter", None)
    if pending_rf is not None:
        if pending_rf.get("clear_other"):
            _clear_planning_flex_filter_state(clear_tracking=True)
            st.session_state["ms_planning_tag_filter"] = []
            st.session_state["last_planning_tag_filter"] = []
        if "target_pids" in pending_rf:
            st.session_state["ms_multi_projects"] = pending_rf["target_pids"]

    pending_project_filter = st.session_state.pop("pending_project_context_filter", None)
    if isinstance(pending_project_filter, dict):
        _focus_planning_on_project(pending_project_filter)

    # Top Active Resource Pool Filter Banner
    active_rf = st.session_state.get("active_resource_pool_filter")
    if active_rf:
        f_pool_name = active_rf.get("pool_name", "Pool")
        f_start = active_rf.get("start_date", "")
        f_end = active_rf.get("end_date", "")
        f_count = active_rf.get("count", 0)

        b_info, b_btn = st.columns([5, 1])
        with b_info:
            st.info(
                f"🔍 **Active Filter from Resource Pool**: Showing {f_count} projects consuming "
                f"**{f_pool_name}** during `{f_start} → {f_end}`."
            )
        with b_btn:
            if st.button("✖ Clear Filter", key="btn_clear_pool_filter_top", type="secondary"):
                _handle_clear_resource_pool_filter(master_proj_ids)

    project_filter_frame["_project_tags"] = project_filter_frame["id"].apply(
        lambda project_id: project_tags_by_id.get(int(project_id), [])
    )

    flex_filter_fields: dict[str, str] = {
        t("portfolio.col_name", default="Project name"): "name",
        t("portfolio.col_status", default="Status"): "status",
        t("master_data.field_project_manager", default="Project Manager"): "project_manager",
        t(
            "portfolio.filter_level_3_manager",
            default="Managing Function (Level 3)",
        ): "level_3_manager_name",
        t("planning.flex_filter_project_tags", default="Project Tags"): "_project_tags",
    }
    if not params.empty and "param_id" in params.columns:
        for _, parameter in params.iterrows():
            param_id = str(parameter["param_id"])
            param_name = str(parameter.get("param_name", param_id))
            target_column = param_id
            if param_id not in project_filter_frame.columns:
                project_filter_frame[param_id] = None
            if target_column is not None:
                field_label = param_name
                if field_label in flex_filter_fields:
                    field_label = f"{param_name} ({param_id})"
                flex_filter_fields[field_label] = target_column

    top_filter_col, top_flex_col, top_sel_col = st.columns([2, 1.2, 3])

    with top_filter_col:
        selected_tag_filters = st.multiselect(
            f"🏷️ {t('planning.filter_by_tags', default='Filter Projects by Tag')}",
            options=available_tags_list,
            help="Filter project list to projects assigned any of the chosen tags.",
            key="ms_planning_tag_filter",
        )

    active_flex_filters: dict[str, list[str]] = {}
    with top_flex_col:
        with st.popover(
            t("planning.flex_filters", default="Flexible filters"),
            icon=":material/filter_alt:",
            width="stretch",
        ):
            selected_flex_fields = st.multiselect(
                t("planning.flex_filter_fields", default="Filter fields"),
                options=list(flex_filter_fields),
                placeholder=t(
                    "planning.flex_filter_fields_placeholder",
                    default="Choose one or more fields",
                ),
                key="planning_flex_fields",
            )
            flex_match_mode = st.segmented_control(
                t(
                    "planning.flex_filter_match_label",
                    default="When several values are selected",
                ),
                options=["Any", "All"],
                default="Any",
                key="planning_flex_match_mode",
                help=t(
                    "planning.flex_filter_match_help",
                    default="Fields use AND. This controls matching within each field.",
                ),
            )
            for field_label in selected_flex_fields:
                target_column = flex_filter_fields[field_label]
                filter_options = _unique_planning_filter_options(
                    project_filter_frame[target_column]
                )
                selected_values = st.multiselect(
                    field_label,
                    options=filter_options,
                    placeholder=t("planning.flex_filter_all_values", default="All values"),
                    key=f"planning_flex_values::{target_column}",
                )
                if selected_values:
                    active_flex_filters[target_column] = selected_values
            st.button(
                t("planning.flex_filter_clear", default="Clear filters"),
                on_click=_clear_planning_flex_filter_state,
                width="stretch",
                disabled=not selected_flex_fields,
                key="btn_clear_planning_flex",
            )

    flex_signature = (
        flex_match_mode,
        tuple(
            sorted(
                (column, tuple(values))
                for column, values in active_flex_filters.items()
            )
        ),
    )
    previous_flex_signature = st.session_state.get("planning_last_flex_signature")
    flex_filters_changed = (
        previous_flex_signature is not None
        and previous_flex_signature != flex_signature
    )
    st.session_state["planning_last_flex_signature"] = flex_signature

    if active_flex_filters:
        project_filter_frame = _apply_planning_flex_filters(
            project_filter_frame,
            active_flex_filters,
            match_all_values=flex_match_mode == "All",
        )
        df_projects = df_projects[
            df_projects["id"].isin(project_filter_frame["id"].tolist())
        ]
        st.caption(
            f"{len(active_flex_filters)} active flexible filter"
            f"{'s' if len(active_flex_filters) != 1 else ''} · "
            f"{len(df_projects)} matching projects"
        )

    prev_tag_filters = st.session_state.get("last_planning_tag_filter", None)
    tag_filters_cleared = bool(prev_tag_filters and not selected_tag_filters)
    tag_filters_changed = bool(
        prev_tag_filters is not None and set(prev_tag_filters) != set(selected_tag_filters)
    )
    st.session_state["last_planning_tag_filter"] = list(selected_tag_filters)

    # Filter projects based on tag selection if any
    if selected_tag_filters and not df_all_proj_tags.empty:
        matching_proj_ids = set()
        for r in project_tag_records:
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

    cur_active_rf = st.session_state.get("active_resource_pool_filter")
    if cur_active_rf and "project_ids" in cur_active_rf:
        rf_pids = [p for p in cur_active_rf["project_ids"] if p in all_proj_ids]
        st.session_state["ms_multi_projects"] = rf_pids
    elif flex_filters_changed:
        st.session_state["ms_multi_projects"] = all_proj_ids
    elif tag_filters_cleared:
        st.session_state["ms_multi_projects"] = all_proj_ids
    elif tag_filters_changed and selected_tag_filters:
        st.session_state["ms_multi_projects"] = all_proj_ids
    elif "ms_multi_projects" in st.session_state:
        st.session_state["ms_multi_projects"] = [
            p for p in st.session_state["ms_multi_projects"] if p in all_proj_ids
        ]
    else:
        st.session_state["ms_multi_projects"] = []  # Empty means all; avoid 10,000 selected chips.

    with top_sel_col:
        multi_header_label = f"🔍 {t('planning.select_multi_proj', default='Select Projects to Display in Multi-Gantt')} ({len(df_projects)} projects found)"
        selected_projects = st.multiselect(
            multi_header_label,
            options=all_proj_ids,
            format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
            key="ms_multi_projects",
        )
        if not selected_projects:
            selected_projects = all_proj_ids

    if not selected_projects:
        if active_rf:
            st.warning(
                f"No projects consume **{active_rf.get('pool_name')}** during `{active_rf.get('start_date')} → {active_rf.get('end_date')}`. "
                "Click 'Clear Filter' above to reset."
            )
            if st.button("✖ Clear Filter", key="btn_clear_empty_rf_filter"):
                _handle_clear_resource_pool_filter(master_proj_ids)
        else:
            st.info(t("planning.no_projects_available", default="No projects available with the current filter."))
        return

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

    edit_project_modal_id = st.session_state.pop("modal_edit_project", None)
    if edit_project_modal_id:
        open_edit_project_dialog(int(edit_project_modal_id), project_repo, schema_repo)

    _render_planning_chart(project_repo, milestone_repo, tag_repo, pool_repo, org_repo,
                           selected_projects, df_projects, proj_map, master_proj_ids,
                           (flex_signature, selected_tag_filters, st.session_state.get('active_resource_pool_filter')))

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
