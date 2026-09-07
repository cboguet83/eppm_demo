"""Screen 5: Organization Structure & Settings Management View with Contextual Menus and Dialogs."""

import datetime
import os
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from src.i18n import t
from src.models.constants import PAGE_PLANNING
from src.models.organization import Employee, EmployeeCalendarException, FunctionType, OrgFunction, Team
from src.models.resource_pool import PoolAssignment, PoolCapacityDetail, PoolMapping, ResourcePool
from src.models.tag import ProjectTag, TagDictionary, TagGroup, TaskTag
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.resource_pool_repo import ResourcePoolRepository
from src.repositories.schema_repo import SchemaRepository
from src.repositories.tag_repo import TagRepository
from src.services.organization_service import OrganizationService
from src.services.resource_pool_service import ResourcePoolService
from src.services.tag_service import TagService
from src.views.schema_def_view import render_schema_definition


# Declare Interactive Table Custom Components
_COMPONENTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "components",
)
_interactive_function_table = components.declare_component(
    "interactive_function_table",
    path=os.path.join(_COMPONENTS_DIR, "function_table"),
)
_interactive_function_type_table = components.declare_component(
    "interactive_function_type_table",
    path=os.path.join(_COMPONENTS_DIR, "function_type_table"),
)
_interactive_team_table = components.declare_component(
    "interactive_team_table",
    path=os.path.join(_COMPONENTS_DIR, "team_table"),
)
_interactive_employee_table = components.declare_component(
    "interactive_employee_table",
    path=os.path.join(_COMPONENTS_DIR, "employee_table"),
)
_interactive_tag_group_table = components.declare_component(
    "interactive_tag_group_table",
    path=os.path.join(_COMPONENTS_DIR, "tag_group_table"),
)
_interactive_tag_dictionary_table = components.declare_component(
    "interactive_tag_dictionary_table",
    path=os.path.join(_COMPONENTS_DIR, "tag_dictionary_table"),
)
_interactive_project_tag_table = components.declare_component(
    "interactive_project_tag_table",
    path=os.path.join(_COMPONENTS_DIR, "project_tag_table"),
)
_interactive_task_tag_table = components.declare_component(
    "interactive_task_tag_table",
    path=os.path.join(_COMPONENTS_DIR, "task_tag_table"),
)


# =============================================================================
# 1. FUNCTION DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_func", default="➕ Create Job Function"))
def _open_add_function_dialog(
    org_repo: OrganizationRepository,
    df_funcs: pd.DataFrame,
    df_types: pd.DataFrame,
) -> None:
    """Modal dialog to create a new job function."""
    new_name = st.text_input(t("settings.field_func_name", default="Function Title *"), placeholder="e.g. Solution Architect")
    new_level = st.number_input(
        t("settings.field_func_level", default="Hierarchy Level (Integer) *"),
        min_value=1,
        value=1,
        step=1,
    )

    type_opts = [None] + (df_types["function_type_id"].tolist() if not df_types.empty else [])
    type_map = dict(zip(df_types["function_type_id"], df_types["function_type"])) if not df_types.empty else {}
    new_type = st.selectbox(
        t("settings.field_type", default="Function Type"),
        options=type_opts,
        format_func=lambda x: type_map.get(x, "— None") if x is not None else "— None",
    )

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    new_mgr = st.selectbox(
        t("settings.field_primary_mgr", default="Primary Manager Function (Optional)"),
        options=func_opts,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )
    new_dual = st.selectbox(
        t("settings.field_dual_mgr", default="Dual / Matrix Manager Function (Optional)"),
        options=func_opts,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )
    new_fte = st.number_input(
        t("settings.field_fte_pct", default="FTE Workload % (0-100)"),
        min_value=0,
        max_value=100,
        value=100,
        step=5,
    )
    new_has_reports = st.checkbox(
        t("settings.field_has_reports", default="Has Reports / Subordinates"),
        value=False,
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Function"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_function(new_name, int(new_level), int(new_fte))
            new_fid = org_repo.create_function(
                OrgFunction(
                    name=new_name,
                    hierarchy_level=int(new_level),
                    function_type_id=new_type,
                    manager_function_id=new_mgr,
                    dual_manager_function_id=new_dual,
                    fte_percentage=int(new_fte),
                    has_reports=new_has_reports,
                )
            )
            st.toast(t("settings.msg_func_created", name=new_name, default=f"Function '{new_name}' created (ID: {new_fid})!"), icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating function: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_func", default="✏️ Edit Job Function"))
def _open_edit_function_dialog(
    org_repo: OrganizationRepository,
    func_id: int,
    df_funcs: pd.DataFrame,
    df_types: pd.DataFrame,
) -> None:
    """Modal dialog to edit an existing job function."""
    fn_obj = org_repo.get_function_by_id(func_id)
    if not fn_obj:
        st.error("Function not found.")
        return

    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    type_map = dict(zip(df_types["function_type_id"], df_types["function_type"])) if not df_types.empty else {}

    edit_name = st.text_input(t("settings.field_func_name", default="Function Title *"), value=fn_obj.name)
    edit_level = st.number_input(
        t("settings.field_func_level", default="Hierarchy Level (Integer) *"),
        min_value=1,
        value=fn_obj.hierarchy_level,
        step=1,
    )

    type_opts = [None] + (df_types["function_type_id"].tolist() if not df_types.empty else [])
    edit_type_idx = type_opts.index(fn_obj.function_type_id) if fn_obj.function_type_id in type_opts else 0
    edit_type = st.selectbox(
        t("settings.field_type", default="Function Type"),
        options=type_opts,
        index=edit_type_idx,
        format_func=lambda x: type_map.get(x, "— None") if x is not None else "— None",
    )

    mgr_opts = [None] + [fid for fid in df_funcs["function_id"].tolist() if fid != func_id]
    mgr_idx = mgr_opts.index(fn_obj.manager_function_id) if fn_obj.manager_function_id in mgr_opts else 0
    edit_mgr = st.selectbox(
        t("settings.field_primary_mgr", default="Primary Manager Function"),
        options=mgr_opts,
        index=mgr_idx,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    dual_idx = mgr_opts.index(fn_obj.dual_manager_function_id) if fn_obj.dual_manager_function_id in mgr_opts else 0
    edit_dual = st.selectbox(
        t("settings.field_dual_mgr", default="Dual / Matrix Manager Function"),
        options=mgr_opts,
        index=dual_idx,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    edit_fte = st.number_input(
        t("settings.field_fte_pct", default="FTE Workload % (0-100)"),
        min_value=0,
        max_value=100,
        value=fn_obj.fte_percentage if fn_obj.fte_percentage is not None else 100,
        step=5,
    )
    edit_has_reports = st.checkbox(
        t("settings.field_has_reports", default="Has Reports / Subordinates"),
        value=fn_obj.has_reports,
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_function(edit_name, int(edit_level), int(edit_fte))
            org_repo.update_function(
                OrgFunction(
                    function_id=func_id,
                    name=edit_name,
                    hierarchy_level=int(edit_level),
                    function_type_id=edit_type,
                    manager_function_id=edit_mgr,
                    dual_manager_function_id=edit_dual,
                    fte_percentage=int(edit_fte),
                    has_reports=edit_has_reports,
                )
            )
            st.toast(t("settings.msg_func_updated", default="Function updated successfully!"), icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating function: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_function_dialog(
    org_repo: OrganizationRepository,
    func_id: int,
    func_name: str,
) -> None:
    """Modal dialog to confirm deletion of a job function."""
    st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=func_name, default=f'Are you sure you want to delete Function **{func_name}** (ID: {func_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        org_repo.delete_function(func_id)
        st.toast(t("settings.msg_func_deleted", default=f"Function '{func_name}' deleted."), icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# 3. TEAM DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_team", default="➕ Create Team"))
def _open_add_team_dialog(
    org_repo: OrganizationRepository,
    df_funcs: pd.DataFrame,
    pool_repo: Optional[ResourcePoolRepository] = None,
) -> None:
    """Modal dialog to create a new team."""
    new_name = st.text_input(t("settings.field_team_name", default="Team Name *"), placeholder="e.g. Equipe BIM")

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}

    new_mgr = st.selectbox(
        t("settings.field_team_mgr", default="Manager Function (Optional)"),
        options=func_opts,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )
    new_leader = st.selectbox(
        t("settings.field_team_leader", default="Team Leader Function (Optional)"),
        options=func_opts,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    member_opts = df_funcs["function_id"].tolist() if not df_funcs.empty else []
    new_members = st.multiselect(
        t("settings.field_team_members", default="Team Member Functions"),
        options=member_opts,
        format_func=lambda x: func_map.get(x, f"Function #{x}"),
        help="Select functions belonging to this team.",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Team"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_team(new_name)
            new_tid = org_repo.create_team(
                Team(
                    team_name=new_name,
                    manager_function_id=new_mgr,
                    leader_function_id=new_leader,
                )
            )
            if pool_repo and new_members:
                pool_repo.set_team_functions(new_tid, new_members)
            st.toast(t("settings.msg_team_created", name=new_name, default=f"Team '{new_name}' created (ID: {new_tid})!"), icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating team: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_team", default="✏️ Edit Team"))
def _open_edit_team_dialog(
    org_repo: OrganizationRepository,
    team_id: int,
    df_funcs: pd.DataFrame,
    pool_repo: Optional[ResourcePoolRepository] = None,
) -> None:
    """Modal dialog to edit an existing team."""
    team_obj = org_repo.get_team_by_id(team_id)
    if not team_obj:
        st.error("Team not found.")
        return

    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    edit_name = st.text_input(t("settings.field_team_name", default="Team Name *"), value=team_obj.team_name)

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    mgr_idx = func_opts.index(team_obj.manager_function_id) if team_obj.manager_function_id in func_opts else 0
    edit_mgr = st.selectbox(
        t("settings.field_team_mgr", default="Manager Function"),
        options=func_opts,
        index=mgr_idx,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    ldr_idx = func_opts.index(team_obj.leader_function_id) if team_obj.leader_function_id in func_opts else 0
    edit_leader = st.selectbox(
        t("settings.field_team_leader", default="Team Leader Function"),
        options=func_opts,
        index=ldr_idx,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )

    current_members = pool_repo.get_team_functions(team_id) if pool_repo else []
    member_opts = df_funcs["function_id"].tolist() if not df_funcs.empty else []
    edit_members = st.multiselect(
        t("settings.field_team_members", default="Team Member Functions"),
        options=member_opts,
        default=[fid for fid in current_members if fid in member_opts],
        format_func=lambda x: func_map.get(x, f"Function #{x}"),
        help="Select functions belonging to this team.",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_team(edit_name)
            org_repo.update_team(
                Team(
                    team_id=team_id,
                    team_name=edit_name,
                    manager_function_id=edit_mgr,
                    leader_function_id=edit_leader,
                )
            )
            if pool_repo:
                pool_repo.set_team_functions(team_id, edit_members)
            st.toast(t("settings.msg_team_updated", default="Team updated successfully!"), icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating team: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_team_dialog(
    org_repo: OrganizationRepository,
    team_id: int,
    team_name: str,
) -> None:
    """Modal dialog to confirm deletion of a team."""
    st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=team_name, default=f'Are you sure you want to delete Team **{team_name}** (ID: {team_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        org_repo.delete_team(team_id)
        st.toast(t("settings.msg_team_deleted", default=f"Team '{team_name}' deleted."), icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# RESOURCE POOL DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_pool", default="➕ Create Resource Pool"))
def _open_add_pool_dialog(pool_repo: ResourcePoolRepository) -> None:
    """Modal dialog to create a new resource pool."""
    new_name = st.text_input(t("settings.field_pool_name", default="Resource Pool Name *"), placeholder="e.g. Core Engineering Pool")
    new_desc = st.text_area(t("settings.field_pool_desc", default="Description"), placeholder="Purpose and specialty of this pool...")
    new_capacity = st.number_input(
        t("settings.field_pool_capacity", default="Defined capacity (FTE)"),
        min_value=0.0,
        value=0.0,
        step=0.25,
        help=t(
            "settings.field_pool_capacity_help",
            default="Capacity limit used to evaluate project and task demand.",
        ),
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Pool"), type="primary", use_container_width=True):
        try:
            ResourcePoolService.validate_pool_name(new_name)
            ResourcePoolService.validate_capacity_fte(float(new_capacity))
            p_id = pool_repo.create_pool(
                ResourcePool(
                    name=new_name.strip(),
                    description=new_desc.strip(),
                    capacity_fte=float(new_capacity),
                )
            )
            st.toast(f"Resource Pool '{new_name}' created (ID: {p_id})!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating pool: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_pool", default="✏️ Edit Resource Pool"))
def _open_edit_pool_dialog(pool_repo: ResourcePoolRepository, pool_id: int) -> None:
    """Modal dialog to edit an existing resource pool."""
    pool = pool_repo.get_pool_by_id(pool_id)
    if not pool:
        st.error("Resource pool not found.")
        return

    edit_name = st.text_input(t("settings.field_pool_name", default="Resource Pool Name *"), value=pool.name)
    edit_desc = st.text_area(t("settings.field_pool_desc", default="Description"), value=pool.description)
    edit_capacity = st.number_input(
        t("settings.field_pool_capacity", default="Defined capacity (FTE)"),
        min_value=0.0,
        value=float(pool.capacity_fte or 0.0),
        step=0.25,
        help=t(
            "settings.field_pool_capacity_help",
            default="Capacity limit used to evaluate project and task demand.",
        ),
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            ResourcePoolService.validate_pool_name(edit_name)
            ResourcePoolService.validate_capacity_fte(float(edit_capacity))
            pool_repo.update_pool(
                ResourcePool(
                    id=pool_id,
                    name=edit_name.strip(),
                    description=edit_desc.strip(),
                    capacity_fte=float(edit_capacity),
                )
            )
            st.toast("Resource Pool updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating pool: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_pool_dialog(pool_repo: ResourcePoolRepository, pool_id: int, pool_name: str) -> None:
    """Modal dialog to confirm deletion of a resource pool."""
    st.warning(f"⚠️ Are you sure you want to delete Resource Pool **{pool_name}** (ID: #{pool_id})?")
    st.caption("All mappings and project/task assignments linked to this pool will also be deleted.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        pool_repo.delete_pool(pool_id)
        st.toast(f"Resource Pool '{pool_name}' deleted.", icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_add_mapping", default="➕ Assign Team or Employee to Pool"))
def _open_add_pool_mapping_dialog(
    pool_repo: ResourcePoolRepository,
    pool_id: int,
    df_teams: pd.DataFrame,
    df_employees: pd.DataFrame,
) -> None:
    """Modal dialog to assign a team or employee to a resource pool."""
    map_type = st.segmented_control(
        t("settings.mapping_target_type", default="Mapping Target Type"),
        options=["team", "employee"],
        format_func=lambda x: "Team" if x == "team" else "Employee",
        default="team",
    )

    if map_type == "team":
        if df_teams.empty:
            st.warning("No teams available.")
            return
        team_map = dict(zip(df_teams["team_id"], df_teams["team_name"]))
        target_id = st.selectbox(
            t("settings.select_team", default="Select Team"),
            options=df_teams["team_id"].tolist(),
            format_func=lambda tid: f"{team_map.get(tid, f'Team #{tid}')} [#{tid}]",
        )
    else:
        if df_employees.empty:
            st.warning("No employees available.")
            return
        employee_map = {
            int(row["employee_id"]): (
                f"{str(row['firstname']).strip()} {str(row['lastname']).strip()}".strip()
            )
            for _, row in df_employees.iterrows()
        }
        target_id = st.selectbox(
            t("settings.select_employee", default="Select employee"),
            options=df_employees["employee_id"].tolist(),
            format_func=lambda eid: f"{employee_map.get(int(eid), f'Employee #{eid}')} [#{eid}]",
        )

    alloc_pct = st.slider(
        t("settings.field_allocation_pct", default="Pool Allocation Percentage (%)"),
        min_value=0.0,
        max_value=100.0,
        value=100.0,
        step=5.0,
        help="Percentage of this team or employee's capacity allocated to this pool (0% to 100%).",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_mapping", default="💾 Save Mapping"), type="primary", use_container_width=True):
        try:
            ResourcePoolService.validate_allocation_pct(float(alloc_pct))
            pool_repo.create_mapping(
                PoolMapping(
                    pool_id=pool_id,
                    target_type=map_type,
                    target_id=int(target_id),
                    allocation_pct=float(alloc_pct),
                )
            )
            st.toast("Mapping added / updated successfully!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error saving mapping: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


def _append_block_capacity_coords(
    block: list[str],
    cap: float,
    cap_x: list[Optional[str]],
    cap_y: list[Optional[float]],
) -> None:
    """Append capacity limit coordinates for a contiguous date block.

    Args:
        block: List of contiguous ISO-formatted date strings.
        cap: Total pool capacity FTE.
        cap_x: Target list of X coordinate dates.
        cap_y: Target list of Y coordinate capacity values.
    """
    if len(block) == 1:
        d_val = datetime.date.fromisoformat(block[0])
        s_dt = (d_val - datetime.timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        e_dt = (d_val + datetime.timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        cap_x.extend([s_dt, e_dt, None])
        cap_y.extend([cap, cap, None])
    else:
        cap_x.extend([block[0], block[-1], None])
        cap_y.extend([cap, cap, None])


def _append_block_demand_coords(
    block: list[str],
    daily_points: dict[str, float],
    cap: float,
    blue_x: list[Optional[str]],
    blue_y: list[Optional[float]],
    red_x: list[Optional[str]],
    red_y: list[Optional[float]],
) -> None:
    """Append demand line segments for a contiguous date block colored by capacity threshold.

    Args:
        block: List of contiguous ISO-formatted date strings.
        daily_points: Map of ISO date strings to assigned FTE demand.
        cap: Pool capacity limit in FTE.
        blue_x: Target list for within-capacity X coordinates.
        blue_y: Target list for within-capacity Y coordinates.
        red_x: Target list for over-capacity X coordinates.
        red_y: Target list for over-capacity Y coordinates.
    """
    if len(block) < 2:
        return

    for i in range(len(block) - 1):
        d1_str = block[i]
        d2_str = block[i + 1]
        v1 = daily_points[d1_str]
        v2 = daily_points[d2_str]

        is_v1_over = v1 > (cap + 1e-4)
        is_v2_over = v2 > (cap + 1e-4)

        if not is_v1_over and not is_v2_over:
            blue_x.extend([d1_str, d2_str, None])
            blue_y.extend([v1, v2, None])
        elif is_v1_over and is_v2_over:
            red_x.extend([d1_str, d2_str, None])
            red_y.extend([v1, v2, None])
        else:
            d1_dt = datetime.datetime.combine(datetime.date.fromisoformat(d1_str), datetime.time(12, 0))
            d2_dt = datetime.datetime.combine(datetime.date.fromisoformat(d2_str), datetime.time(12, 0))
            denom = v2 - v1
            ratio = (cap - v1) / denom if abs(denom) > 1e-6 else 0.5
            ratio = max(0.01, min(0.99, ratio))
            cross_dt = d1_dt + ratio * (d2_dt - d1_dt)
            cross_str = cross_dt.strftime("%Y-%m-%d %H:%M:%S")

            if not is_v1_over and is_v2_over:
                blue_x.extend([d1_str, cross_str, None])
                blue_y.extend([v1, cap, None])
                red_x.extend([cross_str, d2_str, None])
                red_y.extend([cap, v2, None])
            else:
                red_x.extend([d1_str, cross_str, None])
                red_y.extend([v1, cap, None])
                blue_x.extend([cross_str, d2_str, None])
                blue_y.extend([cap, v2, None])


def _build_pool_timeline_figure(current_detail: PoolCapacityDetail) -> Optional[go.Figure]:
    """Construct Plotly timeline chart for pool daily demand vs capacity.

    Renders daily assigned demand in red when exceeding capacity and blue when
    within capacity. Strict line continuity prevents rendering any lines over
    periods not covered by active assignments.

    Args:
        current_detail: Detailed pool capacity and assignment information.

    Returns:
        Plotly Figure object, or None if no daily usage points exist.
    """
    daily_points = current_detail.daily_usage
    if not daily_points and current_detail.assignments:
        daily_points = {}
        for a in current_detail.assignments:
            ResourcePoolService._accumulate_daily_usage(
                daily_points, a["start_date"], a["end_date"], a["fte_assigned"]
            )

    if not daily_points:
        return None

    cap = float(current_detail.total_capacity_fte)
    sorted_dates = sorted(daily_points.keys())

    # 1. Group active dates into contiguous consecutive-day blocks
    blocks: list[list[str]] = []
    current_block: list[str] = []

    for d_str in sorted_dates:
        if not current_block:
            current_block.append(d_str)
            continue
        prev_dt = datetime.date.fromisoformat(current_block[-1])
        curr_dt = datetime.date.fromisoformat(d_str)
        if (curr_dt - prev_dt).days == 1:
            current_block.append(d_str)
        else:
            blocks.append(current_block)
            current_block = [d_str]

    if current_block:
        blocks.append(current_block)

    # 2. Build segmented coordinates
    blue_x: list[Optional[str]] = []
    blue_y: list[Optional[float]] = []
    red_x: list[Optional[str]] = []
    red_y: list[Optional[float]] = []
    cap_x: list[Optional[str]] = []
    cap_y: list[Optional[float]] = []

    for blk in blocks:
        _append_block_capacity_coords(blk, cap, cap_x, cap_y)
        _append_block_demand_coords(blk, daily_points, cap, blue_x, blue_y, red_x, red_y)

    # 3. Build discrete daily markers
    blue_m_x: list[str] = []
    blue_m_y: list[float] = []
    blue_m_text: list[str] = []
    red_m_x: list[str] = []
    red_m_y: list[float] = []
    red_m_text: list[str] = []

    for d in sorted_dates:
        val = daily_points[d]
        if val > (cap + 1e-4):
            red_m_x.append(d)
            red_m_y.append(val)
            red_m_text.append(f"📅 <b>{d}</b><br>Demand: <b>{val:.2f} FTE</b><br>⚠️ Exceeds capacity by +{val - cap:.2f} FTE")
        else:
            blue_m_x.append(d)
            blue_m_y.append(val)
            blue_m_text.append(f"📅 <b>{d}</b><br>Demand: <b>{val:.2f} FTE</b><br>✅ Within capacity limit ({cap:.2f} FTE)")

    fig = go.Figure()

    if blue_x:
        fig.add_trace(go.Scatter(
            x=blue_x,
            y=blue_y,
            mode="lines",
            name=t("settings.demand_within_cap", default="Daily Demand (≤ Capacity)"),
            line=dict(color="#2563EB", width=3),
            hoverinfo="skip",
        ))

    if red_x:
        fig.add_trace(go.Scatter(
            x=red_x,
            y=red_y,
            mode="lines",
            name=t("settings.demand_over_cap", default="Daily Demand (> Capacity)"),
            line=dict(color="#C41039", width=3),
            hoverinfo="skip",
        ))

    if blue_m_x:
        fig.add_trace(go.Scatter(
            x=blue_m_x,
            y=blue_m_y,
            mode="markers",
            name=t("settings.marker_within_cap", default="Demand (≤ Capacity)"),
            marker=dict(color="#2563EB", size=7, line=dict(color="#FFFFFF", width=1)),
            hovertext=blue_m_text,
            hoverinfo="text",
            showlegend=not bool(blue_x),
        ))

    if red_m_x:
        fig.add_trace(go.Scatter(
            x=red_m_x,
            y=red_m_y,
            mode="markers",
            name=t("settings.marker_over_cap", default="Demand (> Capacity)"),
            marker=dict(color="#C41039", size=9, symbol="diamond", line=dict(color="#FFFFFF", width=1.5)),
            hovertext=red_m_text,
            hoverinfo="text",
            showlegend=not bool(red_x),
        ))

    if cap_x:
        fig.add_trace(go.Scatter(
            x=cap_x,
            y=cap_y,
            mode="lines",
            name=t("settings.pool_capacity_line", default="Pool Capacity Limit"),
            line=dict(color="#10B981", width=2.5, dash="dash"),
            hoverinfo="skip",
        ))

    fig.update_layout(
        height=260,
        margin=dict(l=20, r=20, t=25, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(title=""),
        yaxis=dict(title="FTE"),
        hovermode="closest",
    )
    return fig


def _render_pool_assignments_table(
    assignments: list[dict[str, Any]],
    selected_pool_id: int,
    pool_repo: ResourcePoolRepository,
) -> None:
    """Render active pool allocations table with clickable hyperlinks to Planning view.

    Args:
        assignments: List of pool assignment dictionaries.
        selected_pool_id: ID of currently selected resource pool.
        pool_repo: Repository for resource pool database operations.
    """
    if not assignments:
        st.info(t("settings.no_assignments_for_pool", default="This pool is not currently assigned to any project or task."))
        return

    table_rows: list[str] = []
    for a in assignments:
        p_id = a["project_id"]
        p_name = a["project_name"]
        t_id = a["task_id"]
        t_name = a["task_name"]
        fte = a["fte_assigned"]
        s_date = a["start_date"]
        e_date = a["end_date"]
        is_custom = a.get("is_custom_period", False)
        notes = a.get("notes", "")

        proj_link = (
            f'<a href="?nav=planning&project_id={p_id}" target="_self" '
            f'style="color:#0284C7; font-weight:700; text-decoration:underline;" '
            f'title="Open {p_name} in Planning & Milestones">📁 {p_name} [#{p_id}]</a>'
        )

        if t_id:
            task_link = (
                f'<a href="?nav=planning&project_id={p_id}&task_id={t_id}" target="_self" '
                f'style="color:#0284C7; text-decoration:underline;" '
                f'title="Open Task #{t_id} in Planning">📋 {t_name} [#{t_id}]</a>'
            )
        else:
            task_link = '<span style="color:#64748B; font-style:italic;">— Project Level</span>'

        period_badge = (
            f'<span style="font-size:12px; color:#334155;">{s_date} → {e_date}</span> '
            f'<span style="font-size:10.5px; background:#E2E8F0; color:#475569; padding:1px 5px; border-radius:3px;">'
            f'{"Custom" if is_custom else "Full Project"}</span>'
        )

        jump_btn = (
            f'<a href="?nav=planning&project_id={p_id}{f"&task_id={t_id}" if t_id else ""}" target="_self" '
            f'style="background:#0284C7; color:#FFFFFF; padding:4px 8px; border-radius:4px; font-size:11.5px; '
            f'font-weight:600; text-decoration:none; display:inline-block; white-space:nowrap;">'
            f'📅 Open ➔</a>'
        )

        table_rows.append(
            f'<tr style="border-bottom:1px solid #E2E8F0;">'
            f'<td style="padding:8px 10px; font-weight:600; color:#475569;">#{a["id"]}</td>'
            f'<td style="padding:8px 10px;">{proj_link}</td>'
            f'<td style="padding:8px 10px;">{task_link}</td>'
            f'<td style="padding:8px 10px;"><span style="font-weight:700; color:#0F172A; background:#F1F5F9; padding:2px 7px; border-radius:4px;">{fte:.2f} FTE</span></td>'
            f'<td style="padding:8px 10px;">{period_badge}</td>'
            f'<td style="padding:8px 10px; color:#64748B; font-size:12px;">{notes or "—"}</td>'
            f'<td style="padding:8px 10px; text-align:center;">{jump_btn}</td>'
            f'</tr>'
        )

    header_html = (
        f'<tr style="background:#F8FAFC; border-bottom:2px solid #CBD5E1; color:#475569; font-weight:700; font-size:12px; text-transform:uppercase;">'
        f'<th style="padding:8px 10px; text-align:left;">ID</th>'
        f'<th style="padding:8px 10px; text-align:left;">{t("settings.col_project", default="Project")}</th>'
        f'<th style="padding:8px 10px; text-align:left;">{t("settings.col_task", default="Task / Step")}</th>'
        f'<th style="padding:8px 10px; text-align:left;">{t("master_data.field_fte", default="Assigned FTE")}</th>'
        f'<th style="padding:8px 10px; text-align:left;">{t("master_data.field_period", default="Effective Period")}</th>'
        f'<th style="padding:8px 10px; text-align:left;">{t("master_data.field_notes", default="Notes")}</th>'
        f'<th style="padding:8px 10px; text-align:center;">{t("settings.col_action", default="Action")}</th>'
        f'</tr>'
    )

    full_table_html = (
        f'<div style="overflow-x:auto; border:1px solid #E2E8F0; border-radius:6px; margin-bottom:12px;">'
        f'<table style="width:100%; border-collapse:collapse; font-size:12.5px; text-align:left; background:#FFFFFF;">'
        f'<thead>{header_html}</thead>'
        f'<tbody>{"".join(table_rows)}</tbody>'
        f'</table>'
        f'</div>'
    )

    c_tbl, c_del_assign = st.columns([5, 1])
    with c_tbl:
        st.markdown(full_table_html, unsafe_allow_html=True)
    with c_del_assign:
        del_a_id = st.selectbox(
            "Unassign ID",
            options=[a["id"] for a in assignments],
            key=f"sb_del_assign_{selected_pool_id}",
            label_visibility="collapsed",
        )
        if st.button(t("settings.btn_unassign", default="🗑️ Unassign"), key=f"btn_unassign_{selected_pool_id}", use_container_width=True):
            pool_repo.delete_assignment(del_a_id)
            st.toast(f"Assignment #{del_a_id} removed.", icon="🗑️")
            st.rerun()

        if st.button("📅 " + t("settings.btn_jump_to_planning", default="Open in Planning"), key=f"btn_jump_{selected_pool_id}", use_container_width=True):
            chosen = next((a for a in assignments if a["id"] == del_a_id), None)
            if chosen:
                st.session_state["target_planning_project_id"] = int(chosen["project_id"])
                st.session_state["ms_multi_projects"] = [int(chosen["project_id"])]
                if chosen.get("task_id"):
                    st.session_state["target_planning_task_id"] = int(chosen["task_id"])
                st.session_state["nav_redirect"] = PAGE_PLANNING
                st.rerun()




# =============================================================================
# 3. FUNCTION TYPE DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_type", default="➕ Create Function Type"))
def _open_add_function_type_dialog(org_repo: OrganizationRepository) -> None:
    """Modal dialog to create a new function type."""
    new_name = st.text_input(t("settings.field_type_name", default="Function Type *"), placeholder="e.g. Contractor")

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Type"), type="primary", use_container_width=True):
        clean_name = new_name.strip()
        if clean_name:
            try:
                new_tid = org_repo.create_function_type(FunctionType(function_type=clean_name))
                st.toast(t("settings.msg_type_created", name=clean_name, default=f"Function Type '{clean_name}' created (ID: {new_tid})!"), icon="✅")
                st.rerun()
            except Exception as e:
                st.error(f"Error creating type: {e}")
        else:
            st.error(t("settings.err_type_name_empty", default="Function type name cannot be empty."))

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_type", default="✏️ Edit Function Type"))
def _open_edit_function_type_dialog(
    org_repo: OrganizationRepository,
    type_id: int,
    current_name: str,
) -> None:
    """Modal dialog to edit an existing function type."""
    edit_name = st.text_input(t("settings.field_type_name", default="Function Type *"), value=current_name)

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        clean_name = edit_name.strip()
        if clean_name:
            try:
                org_repo.update_function_type(FunctionType(function_type_id=type_id, function_type=clean_name))
                st.toast(t("settings.msg_type_updated", default="Function Type updated successfully!"), icon="✏️")
                st.rerun()
            except Exception as e:
                st.error(f"Error updating type: {e}")
        else:
            st.error(t("settings.err_type_name_empty", default="Function type name cannot be empty."))

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_function_type_dialog(
    org_repo: OrganizationRepository,
    type_id: int,
    type_name: str,
) -> None:
    """Modal dialog to confirm deletion of a function type."""
    st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=type_name, default=f'Are you sure you want to delete Function Type **{type_name}** (ID: {type_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        org_repo.delete_function_type(type_id)
        st.toast(t("settings.msg_type_deleted", default=f"Function Type '{type_name}' deleted."), icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# 4. EMPLOYEE DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_emp", default="➕ Add New Employee"))
def _open_add_employee_dialog(
    org_repo: OrganizationRepository,
    df_funcs: pd.DataFrame,
) -> None:
    """Modal dialog to create a new employee profile."""
    auto_code = org_repo.generate_next_employee_code()
    c_c1, c_c2 = st.columns(2)
    new_code = c_c1.text_input(t("settings.field_emp_code", default="Employee Code *"), value=auto_code)
    new_sigle = c_c2.text_input(t("settings.field_sigle", default="Sigle / Trigram"), placeholder="e.g. SCO")

    c_n1, c_n2 = st.columns(2)
    new_first = c_n1.text_input(t("settings.field_firstname", default="First Name *"), placeholder="Sarah")
    new_last = c_n2.text_input(t("settings.field_lastname", default="Last Name *"), placeholder="Connor")

    c_m1, c_m2 = st.columns(2)
    new_email = c_m1.text_input(t("settings.field_email", default="Email *"), placeholder="sconnor@enterprise.com")
    new_mobile = c_m2.text_input(t("settings.field_mobile", default="Mobile / Phone"), placeholder="+1-555-0101")

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
    c_role, c_occupation = st.columns([2, 1])
    new_func = c_role.selectbox(
        t("settings.field_function", default="Function Role"),
        options=func_opts,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )
    new_occupation = c_occupation.number_input(
        t("settings.field_occupation_percentage", default="Occupation %"),
        min_value=0.0,
        max_value=100.0,
        value=100.0,
        step=5.0,
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Employee"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_employee(
                new_first, new_last, new_email, new_code, new_occupation
            )
            if org_repo.check_email_exists(new_email):
                st.error(t("settings.err_email_taken", email=new_email, default=f"Email '{new_email}' is already registered."))
            elif org_repo.check_code_exists(new_code):
                st.error(t("settings.err_code_taken", code=new_code, default=f"Employee code '{new_code}' is already taken."))
            else:
                new_eid = org_repo.create_employee(
                    Employee(
                        firstname=new_first,
                        lastname=new_last,
                        email=new_email,
                        mobile=new_mobile,
                        sigle=new_sigle,
                        employee_code=new_code,
                        function_id=new_func,
                        occupation_percentage=new_occupation,
                    )
                )
                st.toast(t("settings.msg_emp_created", name=f"{new_first} {new_last}", default=f"Employee '{new_first} {new_last}' added (ID: {new_eid})!"), icon="✅")
                st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error adding employee: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_emp", default="✏️ Edit Employee Profile"))
def _open_edit_employee_dialog(
    org_repo: OrganizationRepository,
    emp_id: int,
    df_funcs: pd.DataFrame,
) -> None:
    """Modal dialog to edit an existing employee profile."""
    emp_obj = org_repo.get_employee_by_id(emp_id)
    if not emp_obj:
        st.error("Employee not found.")
        return

    func_opts = [None] + (df_funcs["function_id"].tolist() if not df_funcs.empty else [])
    func_map = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}

    c_c1, c_c2 = st.columns(2)
    edit_code = c_c1.text_input(t("settings.field_emp_code", default="Employee Code *"), value=emp_obj.employee_code)
    edit_sigle = c_c2.text_input(t("settings.field_sigle", default="Sigle / Trigram"), value=emp_obj.sigle)

    c_n1, c_n2 = st.columns(2)
    edit_first = c_n1.text_input(t("settings.field_firstname", default="First Name *"), value=emp_obj.firstname)
    edit_last = c_n2.text_input(t("settings.field_lastname", default="Last Name *"), value=emp_obj.lastname)

    c_m1, c_m2 = st.columns(2)
    edit_email = c_m1.text_input(t("settings.field_email", default="Email *"), value=emp_obj.email)
    edit_mobile = c_m2.text_input(t("settings.field_mobile", default="Mobile / Phone"), value=emp_obj.mobile)

    emp_f_idx = func_opts.index(emp_obj.function_id) if emp_obj.function_id in func_opts else 0
    c_role, c_occupation = st.columns([2, 1])
    edit_func = c_role.selectbox(
        t("settings.field_function", default="Function Role"),
        options=func_opts,
        index=emp_f_idx,
        format_func=lambda x: func_map.get(x, "— None") if x is not None else "— None",
    )
    edit_occupation = c_occupation.number_input(
        t("settings.field_occupation_percentage", default="Occupation %"),
        min_value=0.0,
        max_value=100.0,
        value=float(emp_obj.occupation_percentage),
        step=5.0,
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_employee(
                edit_first, edit_last, edit_email, edit_code, edit_occupation
            )
            if org_repo.check_email_exists(edit_email, exclude_id=emp_id):
                st.error(t("settings.err_email_taken", email=edit_email, default=f"Email '{edit_email}' is already registered."))
            elif org_repo.check_code_exists(edit_code, exclude_id=emp_id):
                st.error(t("settings.err_code_taken", code=edit_code, default=f"Employee code '{edit_code}' is already taken."))
            else:
                org_repo.update_employee(
                    Employee(
                        employee_id=emp_id,
                        firstname=edit_first,
                        lastname=edit_last,
                        email=edit_email,
                        mobile=edit_mobile,
                        sigle=edit_sigle,
                        employee_code=edit_code,
                        function_id=edit_func,
                        occupation_percentage=edit_occupation,
                    )
                )
                st.toast(t("settings.msg_emp_updated", default="Employee profile updated successfully!"), icon="✏️")
                st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating employee: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_employee_dialog(
    org_repo: OrganizationRepository,
    emp_id: int,
    emp_name: str,
) -> None:
    """Modal dialog to confirm deletion of an employee profile."""
    st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=emp_name, default=f'Are you sure you want to delete Employee profile **{emp_name}** (ID: {emp_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        org_repo.delete_employee(emp_id)
        st.toast(t("settings.msg_emp_deleted", default=f"Employee '{emp_name}' deleted."), icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_add_calendar_exception", default="Add Calendar Exception"))
def _open_add_employee_calendar_exception_dialog(
    org_repo: OrganizationRepository,
    employee_id: int,
) -> None:
    """Modal dialog to add a temporary employee occupation override."""
    today = datetime.date.today()
    c_start, c_end = st.columns(2)
    start_date = c_start.date_input(t("settings.field_start_date", default="Start date"), value=today)
    end_date = c_end.date_input(t("settings.field_end_date", default="End date"), value=today)
    occupation_percentage = st.number_input(
        t("settings.field_exception_percentage", default="Working percentage during period"),
        min_value=0.0,
        max_value=100.0,
        value=0.0,
        step=5.0,
    )
    reason = st.text_input(
        t("settings.field_exception_reason", default="Reason (optional)"),
        placeholder=t("settings.exception_reason_placeholder", default="e.g. Maternity leave"),
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="Save"), type="primary", use_container_width=True):
        try:
            OrganizationService.validate_employee_calendar_exception(
                start_date, end_date, occupation_percentage
            )
            org_repo.create_employee_calendar_exception(
                EmployeeCalendarException(
                    employee_id=employee_id,
                    start_date=start_date,
                    end_date=end_date,
                    occupation_percentage=occupation_percentage,
                    reason=reason,
                )
            )
            st.toast(t("settings.msg_calendar_exception_created", default="Calendar exception created."), icon="✅")
            st.rerun()
        except (ValueError, TypeError) as err:
            st.error(str(err))
        except Exception as err:
            st.error(f"Error adding calendar exception: {err}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_calendar_exception", default="Edit Calendar Exception"))
def _open_edit_employee_calendar_exception_dialog(
    org_repo: OrganizationRepository,
    exception_id: int,
) -> None:
    """Modal dialog to edit a temporary employee occupation override."""
    exception = org_repo.get_employee_calendar_exception_by_id(exception_id)
    if exception is None:
        st.error(t("settings.err_calendar_exception_not_found", default="Calendar exception not found."))
        return

    c_start, c_end = st.columns(2)
    start_date = c_start.date_input(
        t("settings.field_start_date", default="Start date"), value=exception.start_date
    )
    end_date = c_end.date_input(
        t("settings.field_end_date", default="End date"), value=exception.end_date
    )
    occupation_percentage = st.number_input(
        t("settings.field_exception_percentage", default="Working percentage during period"),
        min_value=0.0,
        max_value=100.0,
        value=float(exception.occupation_percentage),
        step=5.0,
    )
    reason = st.text_input(
        t("settings.field_exception_reason", default="Reason (optional)"),
        value=exception.reason,
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(
        t("settings.btn_save_changes", default="Save Changes"),
        type="primary",
        use_container_width=True,
    ):
        try:
            OrganizationService.validate_employee_calendar_exception(
                start_date, end_date, occupation_percentage
            )
            org_repo.update_employee_calendar_exception(
                EmployeeCalendarException(
                    exception_id=exception.exception_id,
                    employee_id=exception.employee_id,
                    start_date=start_date,
                    end_date=end_date,
                    occupation_percentage=occupation_percentage,
                    reason=reason,
                )
            )
            st.toast(t("settings.msg_calendar_exception_updated", default="Calendar exception updated."), icon="✅")
            st.rerun()
        except (ValueError, TypeError) as err:
            st.error(str(err))
        except Exception as err:
            st.error(f"Error updating calendar exception: {err}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="Confirm Deletion"))
def _open_delete_employee_calendar_exception_dialog(
    org_repo: OrganizationRepository,
    exception_id: int,
) -> None:
    """Modal dialog to confirm deletion of an employee calendar exception."""
    st.warning(
        t(
            "settings.delete_calendar_exception_confirm",
            default="Delete this calendar exception? This action cannot be undone.",
        )
    )
    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(
        t("settings.btn_confirm_delete", default="Yes, Delete"),
        type="primary",
        use_container_width=True,
    ):
        org_repo.delete_employee_calendar_exception(exception_id)
        st.toast(t("settings.msg_calendar_exception_deleted", default="Calendar exception deleted."), icon="🗑️")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# 5. TAG GROUP DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_tag_group", default="➕ Create Tag Group"))
def _open_add_tag_group_dialog(tag_repo: TagRepository) -> None:
    """Modal dialog to create a new tag group."""
    new_name = st.text_input(t("settings.field_group_name", default="Tag Group Name *"), placeholder="e.g. Architecture")

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Group"), type="primary", use_container_width=True):
        try:
            TagService.validate_tag_group(new_name)
            new_id = tag_repo.create_tag_group(TagGroup(tag_group_name=new_name.strip()))
            st.toast(f"Tag Group '{new_name}' created (ID: {new_id})!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating tag group: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_tag_group", default="✏️ Edit Tag Group"))
def _open_edit_tag_group_dialog(tag_repo: TagRepository, group_id: int, current_name: str) -> None:
    """Modal dialog to edit a tag group."""
    st.caption(f"ID: #{group_id}")
    edit_name = st.text_input(t("settings.field_group_name", default="Tag Group Name *"), value=current_name)

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            TagService.validate_tag_group(edit_name)
            tag_repo.update_tag_group(TagGroup(id=group_id, tag_group_name=edit_name.strip()))
            st.toast("Tag Group updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating tag group: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_tag_group_dialog(tag_repo: TagRepository, group_id: int, group_name: str) -> None:
    """Modal dialog to confirm deletion of a tag group."""
    usage_count = tag_repo.count_tags_by_group(group_id)
    if usage_count > 0:
        st.error(f"⚠️ Cannot delete Tag Group **{group_name}** (ID: {group_id}) because {usage_count} dictionary tags belong to it.")
        if st.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
            st.rerun()
        return

    st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=group_name, default=f'Are you sure you want to delete Tag Group **{group_name}** (ID: {group_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        try:
            tag_repo.delete_tag_group(group_id)
            st.toast(f"Tag Group '{group_name}' deleted.", icon="🗑️")
            st.rerun()
        except Exception as e:
            st.error(f"Error deleting tag group: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# 6. TAG DICTIONARY DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_tag", default="➕ Create Tag"))
def _open_add_tag_dialog(tag_repo: TagRepository, df_groups: pd.DataFrame) -> None:
    """Modal dialog to create a new tag in the dictionary."""
    new_tag = st.text_input(t("settings.field_tag_name", default="Tag Label *"), placeholder="e.g. Cloud Native")

    group_opts = [None] + (df_groups["id"].tolist() if not df_groups.empty else [])
    group_map = dict(zip(df_groups["id"], df_groups["tag_group_name"])) if not df_groups.empty else {}
    new_group = st.selectbox(
        t("settings.field_tag_group", default="Tag Group (Optional)"),
        options=group_opts,
        format_func=lambda x: f"📁 {group_map.get(x, '')}" if x is not None else "— None",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Tag"), type="primary", use_container_width=True):
        try:
            TagService.validate_tag(new_tag)
            new_id = tag_repo.create_tag(TagDictionary(tag=new_tag.strip(), tag_group_id=new_group))
            st.toast(f"Tag '{new_tag}' created (ID: {new_id})!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_tag", default="✏️ Edit Tag"))
def _open_edit_tag_dialog(
    tag_repo: TagRepository,
    tag_id: int,
    current_tag: str,
    current_group_id: Optional[int],
    df_groups: pd.DataFrame,
) -> None:
    """Modal dialog to edit a tag in the dictionary."""
    st.caption(f"ID: #{tag_id}")
    edit_tag = st.text_input(t("settings.field_tag_name", default="Tag Label *"), value=current_tag)

    group_opts = [None] + (df_groups["id"].tolist() if not df_groups.empty else [])
    group_map = dict(zip(df_groups["id"], df_groups["tag_group_name"])) if not df_groups.empty else {}
    idx = group_opts.index(current_group_id) if current_group_id in group_opts else 0

    edit_group = st.selectbox(
        t("settings.field_tag_group", default="Tag Group (Optional)"),
        options=group_opts,
        index=idx,
        format_func=lambda x: f"📁 {group_map.get(x, '')}" if x is not None else "— None",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            TagService.validate_tag(edit_tag)
            tag_repo.update_tag(TagDictionary(id=tag_id, tag=edit_tag.strip(), tag_group_id=edit_group))
            st.toast("Tag updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_tag_dialog(tag_repo: TagRepository, tag_id: int, tag_name: str) -> None:
    """Modal dialog to confirm deletion of a dictionary tag."""
    usages = tag_repo.count_tag_usages(tag_id)
    if usages > 0:
        st.warning(f"⚠️ Tag **{tag_name}** is currently assigned to {usages} project(s) or task(s). Deleting it will also remove those tag assignments.")
    else:
        st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=tag_name, default=f'Are you sure you want to delete Tag **{tag_name}** (ID: {tag_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        try:
            tag_repo.delete_tag(tag_id)
            st.toast(f"Tag '{tag_name}' deleted.", icon="🗑️")
            st.rerun()
        except Exception as e:
            st.error(f"Error deleting tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# 7. PROJECT TAG DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_proj_tag", default="➕ Assign Project Tag"))
def _open_add_project_tag_dialog(
    tag_repo: TagRepository,
    df_projects: pd.DataFrame,
    df_tags: pd.DataFrame,
) -> None:
    """Modal dialog to assign a tag to a project."""
    if df_projects.empty:
        st.warning("No projects available.")
        return

    proj_opts = df_projects["id"].tolist()
    proj_map = dict(zip(df_projects["id"], df_projects["name"]))
    selected_proj = st.selectbox(
        t("settings.field_project", default="Project *"),
        options=proj_opts,
        format_func=lambda x: f"#{x} - {proj_map.get(x, '')}",
    )

    tag_opts = [None] + (df_tags["id"].tolist() if not df_tags.empty else [])
    tag_map = dict(zip(df_tags["id"], df_tags["tag"])) if not df_tags.empty else {}
    selected_tag = st.selectbox(
        t("settings.field_dict_tag", default="Dictionary Tag (Optional)"),
        options=tag_opts,
        format_func=lambda x: f"🏷️ {tag_map.get(x, '')}" if x is not None else "— None (Use Free Tag)",
    )

    free_tag_val = st.text_input(
        t("settings.field_free_tag", default="Free-form Tag (Optional)"),
        placeholder="e.g. Q3-Urgent",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Assign Tag"), type="primary", use_container_width=True):
        try:
            TagService.validate_project_tag(selected_proj, selected_tag, free_tag_val)
            pt_id = tag_repo.create_project_tag(
                ProjectTag(project_id=selected_proj, tag_id=selected_tag, free_tag=free_tag_val)
            )
            st.toast(f"Project tag assignment #{pt_id} created!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating project tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_proj_tag", default="✏️ Edit Project Tag Assignment"))
def _open_edit_project_tag_dialog(
    tag_repo: TagRepository,
    pt_id: int,
    current_project_id: int,
    current_tag_id: Optional[int],
    current_free_tag: Optional[str],
    df_projects: pd.DataFrame,
    df_tags: pd.DataFrame,
) -> None:
    """Modal dialog to edit a project tag assignment."""
    st.caption(f"Assignment ID: #{pt_id}")
    proj_opts = df_projects["id"].tolist() if not df_projects.empty else [current_project_id]
    proj_map = dict(zip(df_projects["id"], df_projects["name"])) if not df_projects.empty else {}
    p_idx = proj_opts.index(current_project_id) if current_project_id in proj_opts else 0

    selected_proj = st.selectbox(
        t("settings.field_project", default="Project *"),
        options=proj_opts,
        index=p_idx,
        format_func=lambda x: f"#{x} - {proj_map.get(x, '')}",
    )

    tag_opts = [None] + (df_tags["id"].tolist() if not df_tags.empty else [])
    tag_map = dict(zip(df_tags["id"], df_tags["tag"])) if not df_tags.empty else {}
    t_idx = tag_opts.index(current_tag_id) if current_tag_id in tag_opts else 0

    selected_tag = st.selectbox(
        t("settings.field_dict_tag", default="Dictionary Tag (Optional)"),
        options=tag_opts,
        index=t_idx,
        format_func=lambda x: f"🏷️ {tag_map.get(x, '')}" if x is not None else "— None (Use Free Tag)",
    )

    free_tag_val = st.text_input(
        t("settings.field_free_tag", default="Free-form Tag (Optional)"),
        value=current_free_tag or "",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            TagService.validate_project_tag(selected_proj, selected_tag, free_tag_val)
            tag_repo.update_project_tag(
                ProjectTag(id=pt_id, project_id=selected_proj, tag_id=selected_tag, free_tag=free_tag_val)
            )
            st.toast("Project tag updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating project tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_project_tag_dialog(tag_repo: TagRepository, pt_id: int, tag_label: str) -> None:
    """Modal dialog to confirm deletion of a project tag assignment."""
    st.warning(f"⚠️ Are you sure you want to remove project tag assignment **{tag_label}** (ID: #{pt_id})?")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        tag_repo.delete_project_tag(pt_id)
        st.toast(f"Project tag #{pt_id} deleted.", icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# 8. TASK TAG DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_task_tag", default="➕ Assign Task Tag"))
def _open_add_task_tag_dialog(
    tag_repo: TagRepository,
    df_tasks: pd.DataFrame,
    df_tags: pd.DataFrame,
) -> None:
    """Modal dialog to assign a tag to a task."""
    if df_tasks.empty:
        st.warning("No tasks available.")
        return

    task_opts = df_tasks["id"].tolist()
    task_map = dict(zip(df_tasks["id"], df_tasks["task_name"]))
    selected_task = st.selectbox(
        t("settings.field_task", default="Task *"),
        options=task_opts,
        format_func=lambda x: f"#{x} - {task_map.get(x, '')}",
    )

    tag_opts = [None] + (df_tags["id"].tolist() if not df_tags.empty else [])
    tag_map = dict(zip(df_tags["id"], df_tags["tag"])) if not df_tags.empty else {}
    selected_tag = st.selectbox(
        t("settings.field_dict_tag", default="Dictionary Tag (Optional)"),
        options=tag_opts,
        format_func=lambda x: f"🏷️ {tag_map.get(x, '')}" if x is not None else "— None (Use Free Tag)",
    )

    free_tag_val = st.text_input(
        t("settings.field_free_tag", default="Free-form Tag (Optional)"),
        placeholder="e.g. Needs-Refinement",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Assign Tag"), type="primary", use_container_width=True):
        try:
            TagService.validate_task_tag(selected_task, selected_tag, free_tag_val)
            tt_id = tag_repo.create_task_tag(
                TaskTag(task_id=selected_task, tag_id=selected_tag, free_tag=free_tag_val)
            )
            st.toast(f"Task tag assignment #{tt_id} created!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating task tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.dialog_edit_task_tag", default="✏️ Edit Task Tag Assignment"))
def _open_edit_task_tag_dialog(
    tag_repo: TagRepository,
    tt_id: int,
    current_task_id: int,
    current_tag_id: Optional[int],
    current_free_tag: Optional[str],
    df_tasks: pd.DataFrame,
    df_tags: pd.DataFrame,
) -> None:
    """Modal dialog to edit a task tag assignment."""
    st.caption(f"Assignment ID: #{tt_id}")
    task_opts = df_tasks["id"].tolist() if not df_tasks.empty else [current_task_id]
    task_map = dict(zip(df_tasks["id"], df_tasks["task_name"])) if not df_tasks.empty else {}
    t_idx = task_opts.index(current_task_id) if current_task_id in task_opts else 0

    selected_task = st.selectbox(
        t("settings.field_task", default="Task *"),
        options=task_opts,
        index=t_idx,
        format_func=lambda x: f"#{x} - {task_map.get(x, '')}",
    )

    tag_opts = [None] + (df_tags["id"].tolist() if not df_tags.empty else [])
    tag_map = dict(zip(df_tags["id"], df_tags["tag"])) if not df_tags.empty else {}
    tg_idx = tag_opts.index(current_tag_id) if current_tag_id in tag_opts else 0

    selected_tag = st.selectbox(
        t("settings.field_dict_tag", default="Dictionary Tag (Optional)"),
        options=tag_opts,
        index=tg_idx,
        format_func=lambda x: f"🏷️ {tag_map.get(x, '')}" if x is not None else "— None (Use Free Tag)",
    )

    free_tag_val = st.text_input(
        t("settings.field_free_tag", default="Free-form Tag (Optional)"),
        value=current_free_tag or "",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", use_container_width=True):
        try:
            TagService.validate_task_tag(selected_task, selected_tag, free_tag_val)
            tag_repo.update_task_tag(
                TaskTag(id=tt_id, task_id=selected_task, tag_id=selected_tag, free_tag=free_tag_val)
            )
            st.toast("Task tag updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating task tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_task_tag_dialog(tag_repo: TagRepository, tt_id: int, tag_label: str) -> None:
    """Modal dialog to confirm deletion of a task tag assignment."""
    st.warning(f"⚠️ Are you sure you want to remove task tag assignment **{tag_label}** (ID: #{tt_id})?")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", use_container_width=True):
        tag_repo.delete_task_tag(tt_id)
        st.toast(f"Task tag #{tt_id} deleted.", icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), use_container_width=True):
        st.rerun()


# =============================================================================
# MAIN SETTINGS VIEW ENTRYPOINT
# =============================================================================
def render_settings_view(
    org_repo: OrganizationRepository,
    tag_repo: Optional[TagRepository] = None,
    project_repo: Optional[ProjectRepository] = None,
    milestone_repo: Optional[MilestoneRepository] = None,
    pool_repo: Optional[ResourcePoolRepository] = None,
    schema_repo: Optional[SchemaRepository] = None,
) -> None:
    """Renders the Settings screen with sections for Organization Structure and Parameter Definition."""
    st.header(f"⚙️ {t('settings.title', default='Settings')}")

    schema_repo = schema_repo or SchemaRepository(org_repo.db_path)

    # Top-level Section Selector: Organization Structure vs. Parameter Definition
    default_section_idx = 0
    if st.session_state.get("settings_active_section") == "parameters":
        default_section_idx = 1

    selected_section = st.radio(
        "Settings Section",
        options=["org_structure", "param_def"],
        format_func=lambda s: f"🏢 {t('settings.section_org_structure', default='Organization Structure')}"
        if s == "org_structure"
        else f"🧩 {t('settings.section_param_definition', default='Parameter Definition')}",
        index=default_section_idx,
        horizontal=True,
        label_visibility="collapsed",
        key="rb_settings_section",
    )

    if selected_section == "param_def":
        render_schema_definition(schema_repo)
        return

    tag_repo = tag_repo or TagRepository(org_repo.db_path)
    project_repo = project_repo or ProjectRepository(org_repo.db_path)
    milestone_repo = milestone_repo or MilestoneRepository(org_repo.db_path)
    pool_repo = pool_repo or ResourcePoolRepository(org_repo.db_path)

    (
        tab_funcs,
        tab_types,
        tab_teams,
        tab_emps,
        tab_tag_groups,
        tab_tag_dict,
        tab_proj_tags,
        tab_task_tags,
        tab_pools,
    ) = st.tabs([
        f"💼 {t('settings.tab_functions', default='Functions')}",
        f"🏷️ {t('settings.tab_types', default='Function Types')}",
        f"🛡️ {t('settings.tab_teams', default='Teams')}",
        f"👥 {t('settings.tab_employees', default='Employees')}",
        f"📁 {t('settings.tab_tag_groups', default='Tag Groups')}",
        f"📚 {t('settings.tab_tag_dict', default='Tag Dictionary')}",
        f"📌 {t('settings.tab_proj_tags', default='Project Tags')}",
        f"📋 {t('settings.tab_task_tags', default='Task Tags')}",
        f"🏊 {t('settings.tab_resource_pools', default='Resource Pools')}",
    ])


    df_types = org_repo.get_all_function_types()
    df_funcs = org_repo.get_all_functions()
    df_teams = org_repo.get_all_teams()
    df_emps = org_repo.get_all_employees()

    df_groups = tag_repo.get_all_tag_groups()
    df_tags = tag_repo.get_all_tags()
    df_proj_dict_tags = tag_repo.get_project_tag_group_tags()
    df_task_dict_tags = tag_repo.get_task_tag_group_tags()
    df_proj_tags = tag_repo.get_all_project_tags()
    df_task_tags = tag_repo.get_all_task_tags()
    df_projects = project_repo.get_all_projects()
    df_tasks = milestone_repo.get_all_milestones()

    # =========================================================================
    # TAB 1: FUNCTIONS
    # =========================================================================
    with tab_funcs:
        total_funcs = len(df_funcs)
        total_fte = (df_funcs["fte_percentage"].sum() / 100.0) if not df_funcs.empty and "fte_percentage" in df_funcs.columns else 0.0

        st.subheader(f"{t('settings.functions_title', default='Job Functions Management')} ({total_funcs} {t('settings.stat_functions', default='Functions')} • {total_fte:.2f} {t('settings.stat_fte', default='FTE')})")

        # Interactive Overview Table with Column Filtering & Right-Click Context Menu
        enriched_funcs = OrganizationService.enrich_functions(df_funcs, df_types)
        functions_payload = []
        if not enriched_funcs.empty:
            for row in enriched_funcs.to_dict(orient="records"):
                functions_payload.append({
                    "function_id": int(row["function_id"]),
                    "name": str(row["name"]),
                    "hierarchy_level": int(row["hierarchy_level"]) if pd.notna(row.get("hierarchy_level")) else 1,
                    "has_reports": bool(row.get("has_reports", False)),
                    "function_type_id": int(row["function_type_id"]) if pd.notna(row.get("function_type_id")) else None,
                    "function_type_name": str(row["function_type_name"]) if pd.notna(row.get("function_type_name")) else "—",
                    "manager_function_id": int(row["manager_function_id"]) if pd.notna(row.get("manager_function_id")) else None,
                    "manager_function_name": str(row["manager_function_name"]) if pd.notna(row.get("manager_function_name")) else "—",
                    "dual_manager_function_id": int(row["dual_manager_function_id"]) if pd.notna(row.get("dual_manager_function_id")) else None,
                    "dual_manager_function_name": str(row["dual_manager_function_name"]) if pd.notna(row.get("dual_manager_function_name")) else "—",
                    "fte_percentage": int(row["fte_percentage"]) if pd.notna(row.get("fte_percentage")) else 100,
                })

        table_event = _interactive_function_table(
            functions=functions_payload,
            translations={
                "col_id": "ID",
                "col_func_name": t("settings.col_func_name", default="Function Title"),
                "col_level": t("settings.col_level", default="Hierarchy Level"),
                "col_has_reports": t("settings.col_has_reports", default="Has Reports"),
                "col_type": t("settings.col_type", default="Function Type"),
                "col_primary_mgr": t("settings.col_primary_mgr", default="Primary Manager"),
                "col_dual_mgr": t("settings.col_dual_mgr", default="Dual Manager"),
                "col_fte_pct": t("settings.col_fte_pct", default="FTE %"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "no_functions": t("settings.no_functions", default="No job functions registered."),
                "hint_right_click": t("settings.hint_right_click", default="💡 Right-click any row to Add, Edit, or Delete"),
                "badge_yes": t("settings.badge_yes", default="Yes"),
                "badge_no": t("settings.badge_no", default="No"),
                "stat_functions": t("settings.stat_functions", default="Functions"),
                "stat_fte": t("settings.stat_fte", default="FTE"),
                "filter_all": t("settings.filter_all", default="All"),
                "filter_clear": t("settings.filter_clear", default="Clear Filters"),
                "col_filter_ph": t("settings.col_filter_ph", default="Filter..."),
                "search_values": t("settings.search_values", default="Search values..."),
                "select_all": t("settings.select_all", default="Select All"),
                "clear": t("settings.clear", default="Clear"),
                "apply": t("settings.apply", default="Apply"),
                "selected_count": t("settings.selected_count", default="{count} selected"),
                "blanks": t("settings.blanks", default="(Blanks / None)"),
            },
            key="func_interactive_table",
            default=None,
        )

        # Handle context menu trigger events
        if table_event and isinstance(table_event, dict):
            nonce = table_event.get("nonce")
            last_nonce = st.session_state.get("_last_func_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_func_table_nonce"] = nonce
                action = table_event.get("action")
                if action == "add_function":
                    _open_add_function_dialog(org_repo, df_funcs, df_types)
                elif action == "edit_function":
                    fn_id = table_event.get("function_id")
                    if fn_id is not None:
                        _open_edit_function_dialog(org_repo, int(fn_id), df_funcs, df_types)
                elif action == "delete_function":
                    fn_id = table_event.get("function_id")
                    fn_name = table_event.get("function_name", f"ID {fn_id}")
                    if fn_id is not None:
                        _open_delete_function_dialog(org_repo, int(fn_id), str(fn_name))

    # =========================================================================
    # TAB 3: FUNCTION TYPES
    # =========================================================================
    with tab_types:
        total_types = len(df_types)
        st.subheader(f"{t('settings.types_title', default='Function Types Management')} ({total_types} {t('settings.stat_types', default='Types')})")

        types_payload = []
        if not df_types.empty:
            for row in df_types.to_dict(orient="records"):
                types_payload.append({
                    "function_type_id": int(row["function_type_id"]),
                    "function_type": str(row["function_type"]),
                })

        type_table_event = _interactive_function_type_table(
            types=types_payload,
            translations={
                "col_id": "ID",
                "col_type_name": t("settings.col_type_name", default="Function Type Name"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "no_types": t("settings.no_types", default="No function types registered."),
                "stat_types": t("settings.stat_types", default="Types"),
                "filter_all": t("settings.filter_all", default="All"),
                "filter_clear": t("settings.filter_clear", default="Clear Filters"),
                "col_filter_ph": t("settings.col_filter_ph", default="Filter..."),
                "search_values": t("settings.search_values", default="Search values..."),
                "select_all": t("settings.select_all", default="Select All"),
                "clear": t("settings.clear", default="Clear"),
                "apply": t("settings.apply", default="Apply"),
                "selected_count": t("settings.selected_count", default="{count} selected"),
                "blanks": t("settings.blanks", default="(Blanks / None)"),
            },
            key="type_interactive_table",
            default=None,
        )

        if type_table_event and isinstance(type_table_event, dict):
            nonce = type_table_event.get("nonce")
            last_nonce = st.session_state.get("_last_type_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_type_table_nonce"] = nonce
                action = type_table_event.get("action")
                if action == "add_function_type":
                    _open_add_function_type_dialog(org_repo)
                elif action == "edit_function_type":
                    ft_id = type_table_event.get("function_type_id")
                    ft_name = type_table_event.get("function_type_name", "")
                    if ft_id is not None:
                        _open_edit_function_type_dialog(org_repo, int(ft_id), str(ft_name))
                elif action == "delete_function_type":
                    ft_id = type_table_event.get("function_type_id")
                    ft_name = type_table_event.get("function_type_name", f"ID {ft_id}")
                    if ft_id is not None:
                        _open_delete_function_type_dialog(org_repo, int(ft_id), str(ft_name))

    # =========================================================================
    # TAB 4: TEAMS
    # =========================================================================
    with tab_teams:
        total_teams = len(df_teams)
        st.subheader(f"{t('settings.teams_title', default='Teams Management')} ({total_teams} {t('settings.stat_teams', default='Teams')})")

        enriched_teams = OrganizationService.enrich_teams(df_teams, df_funcs)
        teams_payload = []
        if not enriched_teams.empty:
            for row in enriched_teams.to_dict(orient="records"):
                teams_payload.append({
                    "team_id": int(row["team_id"]),
                    "team_name": str(row["team_name"]),
                    "manager_function_id": int(row["manager_function_id"]) if pd.notna(row.get("manager_function_id")) else None,
                    "manager_function_name": str(row["manager_function_name"]) if pd.notna(row.get("manager_function_name")) else "—",
                    "leader_function_id": int(row["leader_function_id"]) if pd.notna(row.get("leader_function_id")) else None,
                    "leader_function_name": str(row["leader_function_name"]) if pd.notna(row.get("leader_function_name")) else "—",
                })

        team_table_event = _interactive_team_table(
            teams=teams_payload,
            translations={
                "col_id": "ID",
                "col_team_name": t("settings.col_team_name", default="Team Name"),
                "col_team_mgr": t("settings.col_team_mgr", default="Manager Function"),
                "col_team_leader": t("settings.col_team_leader", default="Team Leader"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "no_teams": t("settings.no_teams", default="No teams registered."),
                "stat_teams": t("settings.stat_teams", default="Teams"),
                "filter_all": t("settings.filter_all", default="All"),
                "filter_clear": t("settings.filter_clear", default="Clear Filters"),
                "col_filter_ph": t("settings.col_filter_ph", default="Filter..."),
                "search_values": t("settings.search_values", default="Search values..."),
                "select_all": t("settings.select_all", default="Select All"),
                "clear": t("settings.clear", default="Clear"),
                "apply": t("settings.apply", default="Apply"),
                "selected_count": t("settings.selected_count", default="{count} selected"),
                "blanks": t("settings.blanks", default="(Blanks / None)"),
            },
            key="team_interactive_table",
            default=None,
        )

        if team_table_event and isinstance(team_table_event, dict):
            nonce = team_table_event.get("nonce")
            last_nonce = st.session_state.get("_last_team_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_team_table_nonce"] = nonce
                action = team_table_event.get("action")
                if action == "add_team":
                    _open_add_team_dialog(org_repo, df_funcs, pool_repo)
                elif action == "edit_team":
                    tm_id = team_table_event.get("team_id")
                    if tm_id is not None:
                        _open_edit_team_dialog(org_repo, int(tm_id), df_funcs, pool_repo)
                elif action == "delete_team":
                    tm_id = team_table_event.get("team_id")
                    tm_name = team_table_event.get("team_name", f"ID {tm_id}")
                    if tm_id is not None:
                        _open_delete_team_dialog(org_repo, int(tm_id), str(tm_name))

    # =========================================================================
    # TAB 5: EMPLOYEES
    # =========================================================================
    with tab_emps:
        total_emps = len(df_emps)
        st.subheader(f"{t('settings.employees_title', default='Employee Directory & Profile Management')} ({total_emps} {t('settings.stat_employees', default='Employees')})")

        enriched_emps = OrganizationService.enrich_employees(df_emps, df_funcs, df_types)
        emps_payload = []
        if not enriched_emps.empty:
            for row in enriched_emps.to_dict(orient="records"):
                emps_payload.append({
                    "employee_id": int(row["employee_id"]),
                    "employee_code": str(row.get("employee_code") or ""),
                    "full_name": str(row.get("full_name") or ""),
                    "email": str(row.get("email") or ""),
                    "mobile": str(row.get("mobile") or ""),
                    "sigle": str(row.get("sigle") or ""),
                    "function_id": int(row["function_id"]) if pd.notna(row.get("function_id")) else None,
                    "function_name": str(row.get("function_name") or "—"),
                    "function_type_name": str(row.get("function_type_name") or "—"),
                    "occupation_percentage": float(row.get("occupation_percentage", 100.0)),
                })

        emp_table_event = _interactive_employee_table(
            employees=emps_payload,
            translations={
                "col_emp_code": t("settings.col_emp_code", default="Code"),
                "col_full_name": t("settings.col_full_name", default="Full Name"),
                "col_mobile": t("settings.col_mobile", default="Mobile"),
                "col_sigle": t("settings.col_sigle", default="Sigle"),
                "col_function": t("settings.col_function", default="Function"),
                "col_type": t("settings.col_type", default="Function Type"),
                "col_occupation_percentage": t("settings.col_occupation_percentage", default="Occupation %"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "no_employees": t("settings.no_employees", default="No employees registered."),
                "stat_employees": t("settings.stat_employees", default="Employees"),
                "filter_all": t("settings.filter_all", default="All"),
                "filter_clear": t("settings.filter_clear", default="Clear Filters"),
                "col_filter_ph": t("settings.col_filter_ph", default="Filter..."),
                "search_values": t("settings.search_values", default="Search values..."),
                "select_all": t("settings.select_all", default="Select All"),
                "clear": t("settings.clear", default="Clear"),
                "apply": t("settings.apply", default="Apply"),
                "selected_count": t("settings.selected_count", default="{count} selected"),
                "blanks": t("settings.blanks", default="(Blanks / None)"),
            },
            key="emp_interactive_table",
            default=None,
        )

        if emp_table_event and isinstance(emp_table_event, dict):
            nonce = emp_table_event.get("nonce")
            last_nonce = st.session_state.get("_last_emp_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_emp_table_nonce"] = nonce
                action = emp_table_event.get("action")
                if action == "add_employee":
                    _open_add_employee_dialog(org_repo, df_funcs)
                elif action == "edit_employee":
                    e_id = emp_table_event.get("employee_id")
                    if e_id is not None:
                        _open_edit_employee_dialog(org_repo, int(e_id), df_funcs)
                elif action == "delete_employee":
                    e_id = emp_table_event.get("employee_id")
                    e_name = emp_table_event.get("full_name", f"ID {e_id}")
                    if e_id is not None:
                        _open_delete_employee_dialog(org_repo, int(e_id), str(e_name))

        st.divider()
        st.subheader(t("settings.calendar_exceptions_title", default="Employee Calendar Exceptions"))
        st.caption(
            t(
                "settings.calendar_exceptions_help",
                default=(
                    "Temporarily override an employee's normal occupation percentage over an inclusive "
                    "date range, for example 0% during maternity leave."
                ),
            )
        )

        if df_emps.empty:
            st.info(t("settings.no_employees_for_exceptions", default="Add an employee before creating exceptions."))
        else:
            employee_ids = df_emps["employee_id"].astype(int).tolist()
            employee_labels = {
                int(row["employee_id"]): (
                    f"{row['employee_code']} — {row['lastname'].upper()} {row['firstname']}"
                )
                for row in df_emps.to_dict(orient="records")
            }
            selected_employee_id = st.selectbox(
                t("settings.select_employee_for_exceptions", default="Employee"),
                options=employee_ids,
                format_func=lambda employee_id: employee_labels.get(employee_id, str(employee_id)),
                key="calendar_exception_employee_id",
            )

            selected_employee = org_repo.get_employee_by_id(selected_employee_id)
            effective_today = org_repo.get_effective_occupation_percentage(
                selected_employee_id, datetime.date.today()
            )
            c_normal, c_today, c_add = st.columns([1, 1, 2])
            c_normal.metric(
                t("settings.normal_occupation", default="Normal occupation"),
                f"{selected_employee.occupation_percentage:.1f}%" if selected_employee else "—",
            )
            c_today.metric(
                t("settings.effective_today", default="Effective today"),
                f"{effective_today:.1f}%" if effective_today is not None else "—",
            )
            with c_add:
                st.write("")
                if st.button(
                    t("settings.btn_add_calendar_exception", default="Add calendar exception"),
                    type="primary",
                    use_container_width=True,
                ):
                    _open_add_employee_calendar_exception_dialog(org_repo, selected_employee_id)

            df_exceptions = org_repo.get_employee_calendar_exceptions(selected_employee_id)
            if df_exceptions.empty:
                st.info(
                    t(
                        "settings.no_calendar_exceptions",
                        default="No calendar exceptions are defined for this employee.",
                    )
                )
            else:
                display_exceptions = df_exceptions[
                    ["start_date", "end_date", "occupation_percentage", "reason"]
                ].copy()
                display_exceptions["occupation_percentage"] = display_exceptions[
                    "occupation_percentage"
                ].map(lambda value: f"{float(value):.1f}%")
                display_exceptions.columns = [
                    t("settings.field_start_date", default="Start date"),
                    t("settings.field_end_date", default="End date"),
                    t("settings.col_occupation_percentage", default="Occupation %"),
                    t("settings.field_exception_reason", default="Reason"),
                ]
                st.dataframe(display_exceptions, hide_index=True, use_container_width=True)

                exception_ids = df_exceptions["exception_id"].astype(int).tolist()
                exception_labels = {
                    int(row["exception_id"]): (
                        f"{row['start_date']} → {row['end_date']} · "
                        f"{float(row['occupation_percentage']):.1f}%"
                        + (f" · {row['reason']}" if row.get("reason") else "")
                    )
                    for row in df_exceptions.to_dict(orient="records")
                }
                c_select, c_edit, c_delete = st.columns([4, 1, 1])
                selected_exception_id = c_select.selectbox(
                    t("settings.select_calendar_exception", default="Calendar exception"),
                    options=exception_ids,
                    format_func=lambda exception_id: exception_labels.get(exception_id, str(exception_id)),
                    key=f"calendar_exception_{selected_employee_id}",
                )
                if c_edit.button(
                    t("settings.action_edit", default="Edit"),
                    key=f"edit_calendar_exception_{selected_employee_id}",
                    use_container_width=True,
                ):
                    _open_edit_employee_calendar_exception_dialog(org_repo, selected_exception_id)
                if c_delete.button(
                    t("settings.action_delete", default="Delete"),
                    key=f"delete_calendar_exception_{selected_employee_id}",
                    use_container_width=True,
                ):
                    _open_delete_employee_calendar_exception_dialog(org_repo, selected_exception_id)

    # =========================================================================
    # TAB 5: TAG GROUPS
    # =========================================================================
    with tab_tag_groups:
        total_groups = len(df_groups)
        st.subheader(f"{t('settings.tag_groups_title', default='Tag Groups Taxonomy')} ({total_groups} {t('settings.stat_tag_groups', default='Tag Groups')})")

        groups_payload = []
        if not df_groups.empty:
            for row in df_groups.to_dict(orient="records"):
                gid = int(row["id"])
                count = tag_repo.count_tags_by_group(gid)
                groups_payload.append({
                    "id": gid,
                    "tag_group_name": str(row.get("tag_group_name") or ""),
                    "tag_count": count,
                })

        group_table_event = _interactive_tag_group_table(
            tag_groups=groups_payload,
            translations={
                "col_group_name": t("settings.col_group_name", default="Tag Group Name"),
                "col_tag_count": t("settings.col_tag_count", default="Tags Count"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "filter_clear": t("settings.filter_clear", default="Clear Filters"),
                "stat_tag_groups": t("settings.stat_tag_groups", default="Tag Groups"),
            },
            key="tag_group_interactive_table",
            default=None,
        )

        if group_table_event and isinstance(group_table_event, dict):
            nonce = group_table_event.get("nonce")
            last_nonce = st.session_state.get("_last_tag_group_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_tag_group_table_nonce"] = nonce
                action = group_table_event.get("action")
                if action == "add_tag_group":
                    _open_add_tag_group_dialog(tag_repo)
                elif action == "edit_tag_group":
                    gid = group_table_event.get("group_id")
                    gname = group_table_event.get("tag_group_name", "")
                    if gid is not None:
                        _open_edit_tag_group_dialog(tag_repo, int(gid), str(gname))
                elif action == "delete_tag_group":
                    gid = group_table_event.get("group_id")
                    gname = group_table_event.get("tag_group_name", f"ID {gid}")
                    if gid is not None:
                        _open_delete_tag_group_dialog(tag_repo, int(gid), str(gname))

    # =========================================================================
    # TAB 6: TAG DICTIONARY
    # =========================================================================
    with tab_tag_dict:
        total_tags = len(df_tags)
        st.subheader(f"{t('settings.tag_dict_title', default='Tag Dictionary Taxonomy')} ({total_tags} {t('settings.stat_tags', default='Tags')})")

        tags_payload = []
        if not df_tags.empty:
            for row in df_tags.to_dict(orient="records"):
                tid = int(row["id"])
                usages = tag_repo.count_tag_usages(tid)
                tags_payload.append({
                    "id": tid,
                    "tag": str(row.get("tag") or ""),
                    "tag_group_id": int(row["tag_group_id"]) if pd.notna(row.get("tag_group_id")) else None,
                    "tag_group_name": str(row.get("tag_group_name") or ""),
                    "usage_count": usages,
                })

        tag_table_event = _interactive_tag_dictionary_table(
            tags=tags_payload,
            translations={
                "col_tag": t("settings.col_tag", default="Tag"),
                "col_group_name": t("settings.col_group_name", default="Tag Group Name"),
                "col_usages": t("settings.col_usages", default="Usages"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "filter_clear": t("settings.filter_clear", default="Clear Filters"),
                "stat_tags": t("settings.stat_tags", default="Tags"),
            },
            key="tag_dict_interactive_table",
            default=None,
        )

        if tag_table_event and isinstance(tag_table_event, dict):
            nonce = tag_table_event.get("nonce")
            last_nonce = st.session_state.get("_last_tag_dict_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_tag_dict_table_nonce"] = nonce
                action = tag_table_event.get("action")
                if action == "add_tag":
                    _open_add_tag_dialog(tag_repo, df_groups)
                elif action == "edit_tag":
                    tid = tag_table_event.get("tag_id")
                    tname = tag_table_event.get("tag", "")
                    tg_id = tag_table_event.get("tag_group_id")
                    if tid is not None:
                        _open_edit_tag_dialog(
                            tag_repo,
                            int(tid),
                            str(tname),
                            int(tg_id) if tg_id is not None else None,
                            df_groups,
                        )
                elif action == "delete_tag":
                    tid = tag_table_event.get("tag_id")
                    tname = tag_table_event.get("tag", f"ID {tid}")
                    if tid is not None:
                        _open_delete_tag_dialog(tag_repo, int(tid), str(tname))

    # =========================================================================
    # TAB 7: PROJECT TAGS
    # =========================================================================
    with tab_proj_tags:
        total_proj_tags = len(df_proj_tags)
        st.subheader(f"{t('settings.proj_tags_title', default='Project Tag Assignments')} ({total_proj_tags} {t('settings.stat_project_tags', default='Project Tags')})")

        proj_tags_payload = []
        if not df_proj_tags.empty:
            for row in df_proj_tags.to_dict(orient="records"):
                proj_tags_payload.append({
                    "id": int(row["id"]),
                    "project_id": int(row["project_id"]),
                    "project_name": str(row.get("project_name") or f"Project #{row['project_id']}"),
                    "tag_id": int(row["tag_id"]) if pd.notna(row.get("tag_id")) else None,
                    "tag_name": str(row.get("tag_name") or ""),
                    "tag_group_name": str(row.get("tag_group_name") or ""),
                    "free_tag": str(row.get("free_tag") or ""),
                })

        proj_tag_table_event = _interactive_project_tag_table(
            project_tags=proj_tags_payload,
            translations={
                "col_project": t("settings.col_project", default="Project"),
                "col_tag": t("settings.col_tag", default="Dictionary Tag"),
                "col_group_name": t("settings.col_group_name", default="Tag Group"),
                "col_free_tag": t("settings.col_free_tag", default="Free Tag"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "filter_clear": t("settings.filter_clear", default="Clear Filters"),
                "stat_project_tags": t("settings.stat_project_tags", default="Project Tags"),
            },
            key="proj_tag_interactive_table",
            default=None,
        )

        if proj_tag_table_event and isinstance(proj_tag_table_event, dict):
            nonce = proj_tag_table_event.get("nonce")
            last_nonce = st.session_state.get("_last_proj_tag_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_proj_tag_table_nonce"] = nonce
                action = proj_tag_table_event.get("action")
                if action == "add_project_tag":
                    _open_add_project_tag_dialog(tag_repo, df_projects, df_proj_dict_tags)
                elif action == "edit_project_tag":
                    pt_id = proj_tag_table_event.get("pt_id")
                    p_id = proj_tag_table_event.get("project_id")
                    t_id = proj_tag_table_event.get("tag_id")
                    f_tag = proj_tag_table_event.get("free_tag")
                    if pt_id is not None and p_id is not None:
                        _open_edit_project_tag_dialog(
                            tag_repo,
                            int(pt_id),
                            int(p_id),
                            int(t_id) if t_id is not None else None,
                            str(f_tag) if f_tag else None,
                            df_projects,
                            df_proj_dict_tags,
                        )
                elif action == "delete_project_tag":
                    pt_id = proj_tag_table_event.get("pt_id")
                    t_label = proj_tag_table_event.get("tag_label", f"ID {pt_id}")
                    if pt_id is not None:
                        _open_delete_project_tag_dialog(tag_repo, int(pt_id), str(t_label))

    # =========================================================================
    # TAB 8: TASK TAGS
    # =========================================================================
    with tab_task_tags:
        total_task_tags = len(df_task_tags)
        st.subheader(f"{t('settings.task_tags_title', default='Task Tag Assignments')} ({total_task_tags} {t('settings.stat_task_tags', default='Task Tags')})")

        task_tags_payload = []
        if not df_task_tags.empty:
            for row in df_task_tags.to_dict(orient="records"):
                task_tags_payload.append({
                    "id": int(row["id"]),
                    "task_id": int(row["task_id"]),
                    "task_name": str(row.get("task_name") or f"Task #{row['task_id']}"),
                    "project_name": str(row.get("project_name") or ""),
                    "tag_id": int(row["tag_id"]) if pd.notna(row.get("tag_id")) else None,
                    "tag_name": str(row.get("tag_name") or ""),
                    "tag_group_name": str(row.get("tag_group_name") or ""),
                    "free_tag": str(row.get("free_tag") or ""),
                })

        task_tag_table_event = _interactive_task_tag_table(
            task_tags=task_tags_payload,
            translations={
                "col_task": t("settings.col_task", default="Task"),
                "col_project": t("settings.col_project", default="Project"),
                "col_tag": t("settings.col_tag", default="Dictionary Tag"),
                "col_group_name": t("settings.col_group_name", default="Tag Group"),
                "col_free_tag": t("settings.col_free_tag", default="Free Tag"),
                "action_add": t("settings.action_add", default="Add New"),
                "action_edit": t("settings.action_edit", default="Edit"),
                "action_delete": t("settings.action_delete", default="Delete"),
                "filter_clear": t("settings.filter_clear", default="Clear Filters"),
                "stat_task_tags": t("settings.stat_task_tags", default="Task Tags"),
            },
            key="task_tag_interactive_table",
            default=None,
        )

        if task_tag_table_event and isinstance(task_tag_table_event, dict):
            nonce = task_tag_table_event.get("nonce")
            last_nonce = st.session_state.get("_last_task_tag_table_nonce")
            if nonce and nonce != last_nonce:
                st.session_state["_last_task_tag_table_nonce"] = nonce
                action = task_tag_table_event.get("action")
                if action == "add_task_tag":
                    _open_add_task_tag_dialog(tag_repo, df_tasks, df_task_dict_tags)
                elif action == "edit_task_tag":
                    tt_id = task_tag_table_event.get("tt_id")
                    t_id = task_tag_table_event.get("task_id")
                    tag_id = task_tag_table_event.get("tag_id")
                    f_tag = task_tag_table_event.get("free_tag")
                    if tt_id is not None and t_id is not None:
                        _open_edit_task_tag_dialog(
                            tag_repo,
                            int(tt_id),
                            int(t_id),
                            int(tag_id) if tag_id is not None else None,
                            str(f_tag) if f_tag else None,
                            df_tasks,
                            df_task_dict_tags,
                        )
                elif action == "delete_task_tag":
                    tt_id = task_tag_table_event.get("tt_id")
                    t_label = task_tag_table_event.get("tag_label", f"ID {tt_id}")
                    if tt_id is not None:
                        _open_delete_task_tag_dialog(tag_repo, int(tt_id), str(t_label))

    # =========================================================================
    # TAB 9: RESOURCE POOLS
    # =========================================================================
    with tab_pools:
        all_pool_details = ResourcePoolService.get_portfolio_pools_summary(org_repo, pool_repo, milestone_repo)
        total_pools = len(all_pool_details)
        total_portfolio_capacity = sum(p.total_capacity_fte for p in all_pool_details)
        total_assigned_capacity = sum(p.assigned_capacity_fte for p in all_pool_details)
        peak_portfolio_assigned = sum(p.peak_assigned_fte for p in all_pool_details)
        overassigned_pools_count = sum(1 for p in all_pool_details if p.is_overassigned)

        st.subheader(
            f"🏊 {t('settings.pools_title', default='Resource Pools Management')} "
            f"({total_pools} {t('settings.stat_pools', default='Pools')} • {total_portfolio_capacity:.2f} {t('settings.stat_capacity', default='FTE Capacity')})"
        )

        # 1. Summary KPI Metrics Cards
        kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
        kpi1.metric(t("settings.kpi_total_pools", default="Total Pools"), total_pools)
        kpi2.metric(t("settings.kpi_total_capacity", default="Defined Capacity"), f"{total_portfolio_capacity:.2f} FTE")
        kpi3.metric(
            t("settings.kpi_assigned_capacity", default="Assigned Capacity"),
            f"{total_assigned_capacity:.2f} FTE",
        )
        kpi4.metric(t("settings.kpi_peak_demand", default="Peak Active Demand"), f"{peak_portfolio_assigned:.2f} FTE")
        if overassigned_pools_count > 0:
            kpi5.metric(
                t("settings.kpi_overassigned_pools", default="Overassigned Pools"),
                f"{overassigned_pools_count} ⚠️",
                delta=f"+{overassigned_pools_count} Alert",
                delta_color="inverse",
            )
        else:
            kpi5.metric(t("settings.kpi_overassigned_pools", default="Overassigned Pools"), "0 ✅")

        st.divider()

        # 2. Pool Selection & Action Toolbar
        col_sel, col_add_btn = st.columns([4, 1])
        with col_add_btn:
            if st.button(t("settings.btn_create_pool", default="➕ Create Pool"), type="primary", use_container_width=True):
                _open_add_pool_dialog(pool_repo)

        df_all_pools = pool_repo.get_all_pools()
        if df_all_pools.empty:
            st.info(t("settings.no_pools_registered", default="No resource pools registered yet. Click 'Create Pool' to add one."))
        else:
            pool_id_map = {int(p.pool_id): p for p in all_pool_details}
            pool_options = df_all_pools["id"].tolist()

            with col_sel:
                selected_pool_id = st.selectbox(
                    t("settings.select_pool_to_inspect", default="🔍 Select Resource Pool to Inspect & Configure"),
                    options=pool_options,
                    format_func=lambda pid: (
                        f"🏊 #{pid} - {pool_id_map[pid].pool_name} "
                        f"(Defined {pool_id_map[pid].total_capacity_fte:.2f} FTE | "
                        f"Assigned {pool_id_map[pid].assigned_capacity_fte:.2f} FTE "
                        f"{'| ⚠️ OVERASSIGNED' if pool_id_map[pid].is_overassigned else '| ✅ OK'})"
                        if pid in pool_id_map else f"Pool #{pid}"
                    ),
                    key="sb_selected_resource_pool",
                )

            current_detail = pool_id_map.get(selected_pool_id)
            if current_detail:
                # Pool Details & Action Row
                c_info, c_actions = st.columns([4, 1])
                with c_info:
                    st.markdown(f"### 🏊 **{current_detail.pool_name}** `[Pool #{current_detail.pool_id}]`")
                    pool_obj = pool_repo.get_pool_by_id(selected_pool_id)
                    if pool_obj and pool_obj.description:
                        st.caption(f"📝 {pool_obj.description}")
                with c_actions:
                    c_edit, c_del = st.columns(2)
                    if c_edit.button("✏️", key=f"btn_edit_pool_{selected_pool_id}", help="Edit pool details"):
                        _open_edit_pool_dialog(pool_repo, selected_pool_id)
                    if c_del.button("🗑️", key=f"btn_del_pool_{selected_pool_id}", help="Delete pool"):
                        _open_delete_pool_dialog(pool_repo, selected_pool_id, current_detail.pool_name)

                # Overassignment Alert Banner if overassigned
                if current_detail.is_overassigned:
                    st.error(
                        f"🚨 **DAILY OVERASSIGNMENT ALERT**: Peak daily demand of **{current_detail.peak_assigned_fte:.2f} FTE** "
                        f"exceeds defined pool capacity of **{current_detail.total_capacity_fte:.2f} FTE** "
                        f"by **+{current_detail.peak_excess_fte:.2f} FTE**!\n\n"
                        f"👥 **Deduplicated assigned capacity**: {current_detail.assigned_capacity_fte:.2f} FTE.\n\n"
                        f"📅 **Overassigned Period(s)**: {', '.join(current_detail.overassignment_intervals) if current_detail.overassignment_intervals else 'Active overlapping assignments'}"
                    )
                else:
                    st.success(
                        f"✅ **CAPACITY NORMAL**: Defined pool capacity is **{current_detail.total_capacity_fte:.2f} FTE**; "
                        f"deduplicated assigned capacity is **{current_detail.assigned_capacity_fte:.2f} FTE**. "
                        f"Peak active daily demand is **{current_detail.peak_assigned_fte:.2f} FTE**."
                    )

                # Daily Demand Timeline Plotly Chart
                if current_detail.assignments:
                    st.write(f"##### 📈 {t('settings.daily_demand_chart', default='Daily Capacity vs. Assigned Demand Timeline')}")
                    chart_fig = _build_pool_timeline_figure(current_detail)
                    if chart_fig is not None:
                        st.plotly_chart(chart_fig, use_container_width=True)

                st.divider()

                # Sub-section 1: Assigned Teams & Employees
                st.write(f"#### 🛡️ / 👤 {t('settings.mapped_teams_funcs', default='Assigned Teams & Employees')} (0% - 100%)")
                df_pool_maps = pool_repo.get_mappings_by_pool(selected_pool_id)
                col_m_add, _ = st.columns([2, 3])
                with col_m_add:
                    if st.button(t("settings.btn_add_mapping", default="➕ Assign Team or Employee"), key=f"btn_add_map_{selected_pool_id}"):
                        _open_add_pool_mapping_dialog(pool_repo, selected_pool_id, df_teams, df_emps)

                if df_pool_maps.empty:
                    st.info(t("settings.no_mappings_in_pool", default="No teams or employees assigned to this pool yet. Click 'Assign Team or Employee' above."))
                else:
                    team_lookup = dict(zip(df_teams["team_id"], df_teams["team_name"])) if not df_teams.empty else {}
                    func_lookup = dict(zip(df_funcs["function_id"], df_funcs["name"])) if not df_funcs.empty else {}
                    employee_lookup = {
                        int(row["employee_id"]): (
                            f"{str(row['firstname']).strip()} {str(row['lastname']).strip()}".strip()
                        )
                        for _, row in df_emps.iterrows()
                    } if not df_emps.empty else {}

                    for _, m_row in df_pool_maps.iterrows():
                        m_id = int(m_row["id"])
                        m_type = str(m_row["target_type"]).lower()
                        m_tid = int(m_row["target_id"])
                        m_pct = float(m_row["allocation_pct"])

                        if m_type == "team":
                            target_label = team_lookup.get(m_tid, f"Team #{m_tid}")
                            icon = "🛡️ Team:"
                        elif m_type == "employee":
                            target_label = employee_lookup.get(m_tid, f"Employee #{m_tid}")
                            icon = "👤 Employee:"
                        else:
                            target_label = func_lookup.get(m_tid, f"Function #{m_tid}")
                            icon = "💼 Legacy function:"

                        mc1, mc2, mc3 = st.columns([3, 2, 1])
                        mc1.markdown(f"**{icon}** `{target_label}` `[#{m_tid}]`")
                        new_pct = mc2.number_input(
                            f"Allocation % (#{m_id})",
                            min_value=0.0,
                            max_value=100.0,
                            value=m_pct,
                            step=5.0,
                            key=f"num_alloc_pct_{m_id}",
                            label_visibility="collapsed",
                        )
                        if abs(new_pct - m_pct) > 0.01:
                            pool_repo.update_mapping(m_id, float(new_pct))
                            st.rerun()

                        if mc3.button("🗑️", key=f"btn_del_map_{m_id}", help="Remove mapping from pool"):
                            pool_repo.delete_mapping(m_id)
                            st.toast("Mapping removed from pool.", icon="🗑️")
                            st.rerun()

                st.divider()

                # Sub-section 2: Deduplicated contributing resource breakdown
                st.write(f"#### 🔍 {t('settings.dedup_breakdown_title', default='Deduplicated Assigned Capacity Breakdown')}")
                st.caption(t("settings.dedup_caption", default="Shows unique employees contributing to assigned capacity. Employees reached through several teams or assigned directly and through a team are counted once."))

                if not current_detail.contributing_functions:
                    st.caption("No contributing functions found.")
                else:
                    dedup_table_data = []
                    for cf in current_detail.contributing_functions:
                        status_str = "✅ Considered Once (Direct Override)" if cf.is_deduplicated else "Standard"
                        dedup_table_data.append({
                            "Resource type": cf.resource_type.title(),
                            "Resource ID": cf.resource_id,
                            "Resource": cf.resource_name,
                            "Function": cf.function_name,
                            "Nominal FTE": f"{cf.nominal_fte:.2f}",
                            "Effective %": f"{cf.effective_allocation_pct:.1f}%",
                            "Effective FTE": f"{cf.effective_fte:.2f}",
                            "Source": f"{cf.source_type.title()} ({cf.source_name})",
                            "Deduplication Rule": status_str,
                        })
                    st.dataframe(pd.DataFrame(dedup_table_data), use_container_width=True, hide_index=True)

                st.divider()

                # Sub-section 3: Assignments on Projects & Tasks
                st.write(f"#### 📁 / 📋 {t('settings.assignments_section_title', default='Active Allocations on Projects & Tasks')}")
                _render_pool_assignments_table(current_detail.assignments, selected_pool_id, pool_repo)
