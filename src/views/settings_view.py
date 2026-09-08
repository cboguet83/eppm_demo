"""Screen 5: Organization Structure & Settings Management View with Contextual Menus and Dialogs."""

import datetime
import os
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.i18n import t
from src.models.constants import PAGE_PLANNING
from src.models.resource_pool import (
    PoolAssignment,
    PoolMapping,
    ResourcePool,
    ResourcePoolGroup,
)
from src.models.tag import ProjectTag, TagDictionary, TagGroup, TaskTag
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.resource_pool_repo import ResourcePoolRepository
from src.repositories.schema_repo import SchemaRepository
from src.repositories.tag_repo import TagRepository
from src.services.resource_pool_service import ResourcePoolService
from src.services.tag_service import TagService
from app.main import (
    create_schema_service, create_project_type_service, create_organization_service,
)
from app.presentation.pages.organization import (
    render_functions, render_function_types, render_teams, render_employees,
)
from app.presentation.pages.schema import render_schema_definition


# Declare Interactive Table Custom Components
_COMPONENTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "components",
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
# RESOURCE POOL DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_pool", default="➕ Create Resource Pool"))
def _open_add_pool_dialog(
    pool_repo: ResourcePoolRepository,
    tag_repo: TagRepository,
) -> None:
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
    df_tags = tag_repo.get_all_tags()
    tag_labels = {
        int(row["id"]): (
            f"{row['tag_group_name']} · {row['tag']}"
            if pd.notna(row.get("tag_group_name"))
            else str(row["tag"])
        )
        for _, row in df_tags.iterrows()
    }
    selected_tag_ids = st.multiselect(
        "Pool tags",
        options=list(tag_labels),
        format_func=lambda tag_id: tag_labels[tag_id],
        placeholder="Select dictionary tags",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Pool"), type="primary", width="stretch"):
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
            tag_repo.set_resource_pool_tags(p_id, selected_tag_ids)
            st.toast(f"Resource Pool '{new_name}' created (ID: {p_id})!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating pool: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.dialog_edit_pool", default="✏️ Edit Resource Pool"))
def _open_edit_pool_dialog(
    pool_repo: ResourcePoolRepository,
    tag_repo: TagRepository,
    pool_id: int,
) -> None:
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
    df_tags = tag_repo.get_all_tags()
    tag_labels = {
        int(row["id"]): (
            f"{row['tag_group_name']} · {row['tag']}"
            if pd.notna(row.get("tag_group_name"))
            else str(row["tag"])
        )
        for _, row in df_tags.iterrows()
    }
    existing_pool_tags = tag_repo.get_resource_pool_tags(pool_id)
    existing_tag_ids = (
        [int(tag_id) for tag_id in existing_pool_tags["tag_id"].tolist()]
        if not existing_pool_tags.empty
        else []
    )
    selected_tag_ids = st.multiselect(
        "Pool tags",
        options=list(tag_labels),
        default=existing_tag_ids,
        format_func=lambda tag_id: tag_labels[tag_id],
        placeholder="Select dictionary tags",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", width="stretch"):
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
            tag_repo.set_resource_pool_tags(pool_id, selected_tag_ids)
            st.toast("Resource Pool updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating pool: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_pool_dialog(pool_repo: ResourcePoolRepository, pool_id: int, pool_name: str) -> None:
    """Modal dialog to confirm deletion of a resource pool."""
    st.warning(f"⚠️ Are you sure you want to delete Resource Pool **{pool_name}** (ID: #{pool_id})?")
    st.caption("All mappings and project/task assignments linked to this pool will also be deleted.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"):
        pool_repo.delete_pool(pool_id)
        st.toast(f"Resource Pool '{pool_name}' deleted.", icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


def _pool_group_option_maps(
    pool_repo: ResourcePoolRepository,
) -> tuple[dict[int, str], dict[int, str]]:
    """Build current resource-pool and group labels for membership controls."""
    pools = pool_repo.get_all_pools()
    groups = pool_repo.get_all_pool_groups()
    pool_labels = {
        int(row["id"]): str(row["name"])
        for _, row in pools.iterrows()
    }
    group_labels = {
        int(row["id"]): str(row["name"])
        for _, row in groups.iterrows()
    }
    return pool_labels, group_labels


@st.dialog("➕ Create pool group")
def _open_add_pool_group_dialog(pool_repo: ResourcePoolRepository) -> None:
    """Create a recursive group and its direct members."""
    pool_labels, group_labels = _pool_group_option_maps(pool_repo)
    name = st.text_input("Group name *", placeholder="e.g. Digital delivery")
    description = st.text_area("Description", placeholder="Purpose of this pool group")
    selected_pool_ids = st.multiselect(
        "Direct pools",
        options=list(pool_labels),
        format_func=lambda pool_id: pool_labels[pool_id],
    )
    selected_group_ids = st.multiselect(
        "Child groups",
        options=list(group_labels),
        format_func=lambda group_id: group_labels[group_id],
        help="Child groups can contain pools or more child groups.",
    )

    save_col, cancel_col = st.columns(2)
    if save_col.button("💾 Save group", type="primary", width="stretch"):
        created_group_id: Optional[int] = None
        try:
            created_group_id = pool_repo.create_pool_group(
                ResourcePoolGroup(name=name, description=description)
            )
            pool_repo.replace_group_members(
                created_group_id,
                selected_pool_ids,
                selected_group_ids,
            )
            st.toast(f"Pool group '{name}' created.", icon="✅")
            st.rerun()
        except Exception as exc:
            if created_group_id is not None:
                pool_repo.delete_pool_group(created_group_id)
            st.error(f"Could not create pool group: {exc}")
    if cancel_col.button("Cancel", width="stretch"):
        st.rerun()


@st.dialog("✏️ Edit pool group")
def _open_edit_pool_group_dialog(
    pool_repo: ResourcePoolRepository,
    group_id: int,
) -> None:
    """Edit a recursive group while excluding child choices that form cycles."""
    group = pool_repo.get_pool_group_by_id(group_id)
    if group is None:
        st.error("Pool group not found.")
        return

    pool_labels, group_labels = _pool_group_option_maps(pool_repo)
    current_pool_ids, current_child_ids = pool_repo.get_group_direct_member_ids(group_id)
    safe_group_labels = {
        candidate_id: label
        for candidate_id, label in group_labels.items()
        if candidate_id != group_id
        and (
            candidate_id in current_child_ids
            or not pool_repo.would_create_group_cycle(group_id, candidate_id)
        )
    }

    name = st.text_input("Group name *", value=group.name)
    description = st.text_area("Description", value=group.description)
    selected_pool_ids = st.multiselect(
        "Direct pools",
        options=list(pool_labels),
        default=current_pool_ids,
        format_func=lambda pool_id: pool_labels[pool_id],
    )
    selected_group_ids = st.multiselect(
        "Child groups",
        options=list(safe_group_labels),
        default=current_child_ids,
        format_func=lambda child_id: safe_group_labels[child_id],
        help="Groups that would introduce a direct or indirect loop are excluded.",
    )

    save_col, cancel_col = st.columns(2)
    if save_col.button("💾 Save changes", type="primary", width="stretch"):
        try:
            pool_repo.replace_group_members(group_id, selected_pool_ids, selected_group_ids)
            pool_repo.update_pool_group(
                ResourcePoolGroup(id=group_id, name=name, description=description)
            )
            st.toast("Pool group updated.", icon="✅")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not update pool group: {exc}")
    if cancel_col.button("Cancel", width="stretch"):
        st.rerun()


@st.dialog("🗑️ Delete pool group")
def _open_delete_pool_group_dialog(
    pool_repo: ResourcePoolRepository,
    group_id: int,
    group_name: str,
) -> None:
    """Confirm deletion of a pool group without deleting its member pools."""
    st.warning(f"Delete pool group **{group_name}**?")
    st.caption("Member pools and child groups are retained; only group memberships are removed.")
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button("🗑️ Delete group", type="primary", width="stretch"):
        pool_repo.delete_pool_group(group_id)
        st.toast(f"Pool group '{group_name}' deleted.", icon="🗑️")
        st.rerun()
    if cancel_col.button("Cancel", width="stretch"):
        st.rerun()


def _render_pool_groups_management(pool_repo: ResourcePoolRepository) -> None:
    """Render creation, editing, and recursive membership inspection for pool groups."""
    expander = st.expander("🗂️ Recursive pool groups", expanded=False, on_change="rerun")
    if not expander.open:
        return
    with expander:
        title_col, create_col = st.columns([4, 1])
        title_col.caption(
            "Groups may contain resource pools or other groups. Recursive membership is "
            "deduplicated and loop-safe."
        )
        if create_col.button("➕ New group", width="stretch"):
            _open_add_pool_group_dialog(pool_repo)

        groups = pool_repo.get_all_pool_groups()
        if groups.empty:
            st.info("No pool groups yet.")
            return

        st.dataframe(
            groups[
                [
                    "name",
                    "description",
                    "direct_pool_count",
                    "child_group_count",
                    "recursive_pool_count",
                ]
            ],
            column_config={
                "name": "Group",
                "description": "Description",
                "direct_pool_count": "Direct pools",
                "child_group_count": "Child groups",
                "recursive_pool_count": "All pools",
            },
            hide_index=True,
            width="stretch",
        )

        group_labels = {
            int(row["id"]): str(row["name"])
            for _, row in groups.iterrows()
        }
        selected_group_id = st.selectbox(
            "Inspect group",
            options=list(group_labels),
            format_func=lambda group_id: group_labels[group_id],
            key="selected_resource_pool_group",
        )
        edit_col, delete_col, _ = st.columns([1, 1, 3])
        if edit_col.button("✏️ Edit", width="stretch"):
            _open_edit_pool_group_dialog(pool_repo, selected_group_id)
        if delete_col.button("🗑️ Delete", width="stretch"):
            _open_delete_pool_group_dialog(
                pool_repo,
                selected_group_id,
                group_labels[selected_group_id],
            )

        direct_members = pool_repo.get_group_members(selected_group_id)
        all_pool_ids = pool_repo.get_group_descendant_pool_ids(selected_group_id)
        all_pools = pool_repo.get_all_pools()
        pool_names = {
            int(row["id"]): str(row["name"])
            for _, row in all_pools.iterrows()
        }
        direct_labels = (
            [
                f"{'Pool' if row['member_type'] == 'pool' else 'Group'}: {row['member_name']}"
                for _, row in direct_members.iterrows()
            ]
            if not direct_members.empty
            else []
        )
        st.caption(
            "Direct members: " + (" · ".join(direct_labels) if direct_labels else "None")
        )
        st.write(
            "Resolved pools:",
            ", ".join(pool_names.get(pool_id, f"Pool #{pool_id}") for pool_id in all_pool_ids)
            or "None",
        )


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
    if col_save.button(t("settings.btn_save_mapping", default="💾 Save Mapping"), type="primary", width="stretch"):
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

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


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
        if st.button(t("settings.btn_unassign", default="🗑️ Unassign"), key=f"btn_unassign_{selected_pool_id}", width="stretch"):
            pool_repo.delete_assignment(del_a_id)
            st.toast(f"Assignment #{del_a_id} removed.", icon="🗑️")
            st.rerun()

        if st.button("📅 " + t("settings.btn_jump_to_planning", default="Open in Planning"), key=f"btn_jump_{selected_pool_id}", width="stretch"):
            chosen = next((a for a in assignments if a["id"] == del_a_id), None)
            if chosen:
                st.session_state["target_planning_project_id"] = int(chosen["project_id"])
                st.session_state["ms_multi_projects"] = [int(chosen["project_id"])]
                if chosen.get("task_id"):
                    st.session_state["target_planning_task_id"] = int(chosen["task_id"])
                st.session_state["nav_redirect"] = PAGE_PLANNING
                st.rerun()


# =============================================================================
# 5. TAG GROUP DIALOGS
# =============================================================================
@st.dialog(t("settings.dialog_add_tag_group", default="➕ Create Tag Group"))
def _open_add_tag_group_dialog(tag_repo: TagRepository) -> None:
    """Modal dialog to create a new tag group."""
    new_name = st.text_input(t("settings.field_group_name", default="Tag Group Name *"), placeholder="e.g. Architecture")

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save", default="💾 Save Group"), type="primary", width="stretch"):
        try:
            TagService.validate_tag_group(new_name)
            new_id = tag_repo.create_tag_group(TagGroup(tag_group_name=new_name.strip()))
            st.toast(f"Tag Group '{new_name}' created (ID: {new_id})!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating tag group: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.dialog_edit_tag_group", default="✏️ Edit Tag Group"))
def _open_edit_tag_group_dialog(tag_repo: TagRepository, group_id: int, current_name: str) -> None:
    """Modal dialog to edit a tag group."""
    st.caption(f"ID: #{group_id}")
    edit_name = st.text_input(t("settings.field_group_name", default="Tag Group Name *"), value=current_name)

    col_save, col_cancel = st.columns(2)
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", width="stretch"):
        try:
            TagService.validate_tag_group(edit_name)
            tag_repo.update_tag_group(TagGroup(id=group_id, tag_group_name=edit_name.strip()))
            st.toast("Tag Group updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating tag group: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_tag_group_dialog(tag_repo: TagRepository, group_id: int, group_name: str) -> None:
    """Modal dialog to confirm deletion of a tag group."""
    usage_count = tag_repo.count_tags_by_group(group_id)
    if usage_count > 0:
        st.error(f"⚠️ Cannot delete Tag Group **{group_name}** (ID: {group_id}) because {usage_count} dictionary tags belong to it.")
        if st.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
            st.rerun()
        return

    st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=group_name, default=f'Are you sure you want to delete Tag Group **{group_name}** (ID: {group_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"):
        try:
            tag_repo.delete_tag_group(group_id)
            st.toast(f"Tag Group '{group_name}' deleted.", icon="🗑️")
            st.rerun()
        except Exception as e:
            st.error(f"Error deleting tag group: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
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
    if col_save.button(t("settings.btn_save", default="💾 Save Tag"), type="primary", width="stretch"):
        try:
            TagService.validate_tag(new_tag)
            new_id = tag_repo.create_tag(TagDictionary(tag=new_tag.strip(), tag_group_id=new_group))
            st.toast(f"Tag '{new_tag}' created (ID: {new_id})!", icon="✅")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error creating tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
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
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", width="stretch"):
        try:
            TagService.validate_tag(edit_tag)
            tag_repo.update_tag(TagDictionary(id=tag_id, tag=edit_tag.strip(), tag_group_id=edit_group))
            st.toast("Tag updated successfully!", icon="✏️")
            st.rerun()
        except ValueError as val_err:
            st.error(str(val_err))
        except Exception as e:
            st.error(f"Error updating tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_tag_dialog(tag_repo: TagRepository, tag_id: int, tag_name: str) -> None:
    """Modal dialog to confirm deletion of a dictionary tag."""
    usages = tag_repo.count_tag_usages(tag_id)
    if usages > 0:
        st.warning(
            f"⚠️ Tag **{tag_name}** currently has {usages} project, task, or "
            "resource-pool assignment(s). Deleting it will also remove those assignments."
        )
    else:
        st.warning(f"⚠️ {t('settings.delete_confirm_msg', name=tag_name, default=f'Are you sure you want to delete Tag **{tag_name}** (ID: {tag_id})?')}")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"):
        try:
            tag_repo.delete_tag(tag_id)
            st.toast(f"Tag '{tag_name}' deleted.", icon="🗑️")
            st.rerun()
        except Exception as e:
            st.error(f"Error deleting tag: {e}")

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
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
    if col_save.button(t("settings.btn_save", default="💾 Assign Tag"), type="primary", width="stretch"):
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

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
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
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", width="stretch"):
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

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_project_tag_dialog(tag_repo: TagRepository, pt_id: int, tag_label: str) -> None:
    """Modal dialog to confirm deletion of a project tag assignment."""
    st.warning(f"⚠️ Are you sure you want to remove project tag assignment **{tag_label}** (ID: #{pt_id})?")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"):
        tag_repo.delete_project_tag(pt_id)
        st.toast(f"Project tag #{pt_id} deleted.", icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


# =============================================================================
# 8. TASK TAG DIALOGS
# =============================================================================
def _select_task_for_tag(milestone_repo: MilestoneRepository, *, key: str,
                         current_task_id: Optional[int] = None) -> Optional[int]:
    search = st.text_input("Find task by name, project or #ID", key=f"{key}_search")
    choices = milestone_repo.search_task_choices(search)
    if current_task_id is not None and not any(row["id"] == current_task_id for row in choices):
        current = milestone_repo.get_milestone_by_id(current_task_id)
        if current:
            choices.insert(0, current)
    labels = {row["id"]: f"#{row['id']} — {row['task_name']} · {row.get('project_name', '')}" for row in choices}
    options = list(labels)
    st.caption("Up to 50 matching tasks. Refine the search or enter an exact task ID.")
    return st.selectbox(
        t("settings.field_task", default="Task *"), options=options,
        index=options.index(current_task_id) if current_task_id in options else None,
        format_func=lambda task_id: labels[task_id], key=f"{key}_task",
    )


def _handle_task_tag_query_change() -> None:
    event = st.session_state.get("task_tag_interactive_table")
    if isinstance(event, dict) and event.get("action") == "query_task_tags":
        query = event.get("query", {})
        if isinstance(query, dict):
            st.session_state["task_tag_query"] = {key: query[key] for key in
                ("page", "search", "filters", "sort", "ascending") if key in query}
            st.session_state["_last_task_tag_table_nonce"] = event.get("nonce")
            st.session_state["_last_task_tag_query_nonce"] = event.get("nonce")


@st.dialog(t("settings.dialog_add_task_tag", default="➕ Assign Task Tag"))
def _open_add_task_tag_dialog(
    tag_repo: TagRepository,
    milestone_repo: MilestoneRepository,
) -> None:
    """Modal dialog to assign a tag to a task."""
    selected_task = _select_task_for_tag(milestone_repo, key="add_task_tag")
    df_tags = tag_repo.get_task_tag_group_tags()

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
    if col_save.button(t("settings.btn_save", default="💾 Assign Tag"), type="primary", width="stretch", disabled=selected_task is None):
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

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.dialog_edit_task_tag", default="✏️ Edit Task Tag Assignment"))
def _open_edit_task_tag_dialog(
    tag_repo: TagRepository,
    tt_id: int,
    current_task_id: int,
    current_tag_id: Optional[int],
    current_free_tag: Optional[str],
    milestone_repo: MilestoneRepository,
) -> None:
    """Modal dialog to edit a task tag assignment."""
    st.caption(f"Assignment ID: #{tt_id}")
    selected_task = _select_task_for_tag(milestone_repo, key=f"edit_task_tag_{tt_id}", current_task_id=current_task_id)
    df_tags = tag_repo.get_task_tag_group_tags()

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
    if col_save.button(t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", width="stretch", disabled=selected_task is None):
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

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@st.dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
def _open_delete_task_tag_dialog(tag_repo: TagRepository, tt_id: int, tag_label: str) -> None:
    """Modal dialog to confirm deletion of a task tag assignment."""
    st.warning(f"⚠️ Are you sure you want to remove task tag assignment **{tag_label}** (ID: #{tt_id})?")
    st.caption("This action cannot be undone.")

    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"):
        tag_repo.delete_task_tag(tt_id)
        st.toast(f"Task tag #{tt_id} deleted.", icon="🗑️")
        st.rerun()

    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
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

    # Project roles and event types are independent, lazily loaded catalogs.
    default_section_idx = 0
    if st.session_state.get("settings_active_section") == "parameters":
        default_section_idx = 1

    section_labels = {
        "org_structure": f"🏢 {t('settings.section_org_structure', default='Organization Structure')}",
        "param_def": f"🧩 {t('settings.section_param_definition', default='Parameter Definition')}",
        "project_configuration": t("project_collaboration.configuration", default="Project configuration"),
    }
    selected_section = st.radio(
        "Settings Section",
        options=list(section_labels),
        format_func=section_labels.get,
        index=default_section_idx,
        horizontal=True,
        label_visibility="collapsed",
        key="rb_settings_section",
    )

    if selected_section == "param_def":
        render_schema_definition(
            create_schema_service(schema_repo.db_path), create_project_type_service(schema_repo.db_path),
        )
        return

    if selected_section == "project_configuration":
        from src.views.project_collaboration_view import render_project_catalog
        roles_tab, events_tab = st.tabs([
            t("project_collaboration.roles", default="Project roles"),
            t("project_collaboration.types", default="Event types"),
        ], key="project_configuration_tab", on_change="rerun")
        if roles_tab.open:
            with roles_tab:
                render_project_catalog(org_repo.db_path, "role")
        if events_tab.open:
            with events_tab:
                render_project_catalog(org_repo.db_path, "event_type")
        return

    tag_repo = tag_repo or TagRepository(org_repo.db_path)
    project_repo = project_repo or ProjectRepository(org_repo.db_path)
    milestone_repo = milestone_repo or MilestoneRepository(org_repo.db_path)
    pool_repo = pool_repo or ResourcePoolRepository(org_repo.db_path)

    settings_tab_labels = [
        f"💼 {t('settings.tab_functions', default='Functions')}",
        f"🏷️ {t('settings.tab_types', default='Function Types')}",
        f"🛡️ {t('settings.tab_teams', default='Teams')}",
        f"👥 {t('settings.tab_employees', default='Employees')}",
        f"📁 {t('settings.tab_tag_groups', default='Tag Groups')}",
        f"📚 {t('settings.tab_tag_dict', default='Tag Dictionary')}",
        f"📌 {t('settings.tab_proj_tags', default='Project Tags')}",
        f"📋 {t('settings.tab_task_tags', default='Task Tags')}",
        f"🏊 {t('settings.tab_resource_pools', default='Resource Pools')}",
    ]
    requested_tab = st.session_state.pop("settings_active_tab", None)
    if requested_tab == "resource_pools":
        st.session_state["settings_tab_selection"] = settings_tab_labels[-1]
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
    ) = st.tabs(settings_tab_labels, key="settings_tab_selection", on_change="rerun")


    # =========================================================================
    # TAB 1: FUNCTIONS
    # =========================================================================
    if tab_funcs.open:
        with tab_funcs:
            render_functions(create_organization_service(org_repo.db_path))

    # =========================================================================
    # TAB 3: FUNCTION TYPES
    # =========================================================================
    if tab_types.open:
        with tab_types:
            render_function_types(create_organization_service(org_repo.db_path))

    # =========================================================================
    # TAB 4: TEAMS
    # =========================================================================
    if tab_teams.open:
        with tab_teams:
            render_teams(create_organization_service(org_repo.db_path))

    # =========================================================================
    # TAB 5: EMPLOYEES
    # =========================================================================
    if tab_emps.open:
        with tab_emps:
            render_employees(create_organization_service(org_repo.db_path))

    # =========================================================================
    # TAB 5: TAG GROUPS
    # =========================================================================
    if tab_tag_groups.open:
        with tab_tag_groups:
            df_groups = tag_repo.get_all_tag_groups()
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
    if tab_tag_dict.open:
        with tab_tag_dict:
            df_groups = tag_repo.get_all_tag_groups()
            df_tags = tag_repo.get_all_tags()
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
    if tab_proj_tags.open:
        with tab_proj_tags:
            df_proj_dict_tags = tag_repo.get_project_tag_group_tags()
            df_proj_tags = tag_repo.get_all_project_tags()
            df_projects = project_repo.get_all_projects()
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
    if tab_task_tags.open:
        with tab_task_tags:
            query = st.session_state.get("task_tag_query", {})
            page_data = tag_repo.get_task_tags_page(**query)
            df_task_tags = page_data.pop("rows")
            total_task_tags = page_data["total"]
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
                page_info=page_data,
                query=query,
                query_nonce=st.session_state.get("_last_task_tag_query_nonce"),
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
                on_change=_handle_task_tag_query_change,
            )

            if task_tag_table_event and isinstance(task_tag_table_event, dict):
                nonce = task_tag_table_event.get("nonce")
                last_nonce = st.session_state.get("_last_task_tag_table_nonce")
                if nonce and nonce != last_nonce:
                    st.session_state["_last_task_tag_table_nonce"] = nonce
                    action = task_tag_table_event.get("action")
                    if action == "add_task_tag":
                        _open_add_task_tag_dialog(tag_repo, milestone_repo)
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
                                milestone_repo,
                            )
                    elif action == "delete_task_tag":
                        tt_id = task_tag_table_event.get("tt_id")
                        t_label = task_tag_table_event.get("tag_label", f"ID {tt_id}")
                        if tt_id is not None:
                            _open_delete_task_tag_dialog(tag_repo, int(tt_id), str(t_label))

    # =========================================================================
    # TAB 9: RESOURCE POOLS
    # =========================================================================
    if tab_pools.open:
        with tab_pools:
            df_funcs = org_repo.get_all_functions()
            df_teams = org_repo.get_all_teams()
            df_emps = org_repo.get_all_employees()
            from src.services.pool_capacity_cache import load_pool_capacities

            all_pool_details = load_pool_capacities(pool_repo.db_path)
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
            _render_pool_groups_management(pool_repo)
            st.divider()

            # 2. Pool Selection & Action Toolbar
            col_sel, col_add_btn = st.columns([4, 1])
            with col_add_btn:
                if st.button(t("settings.btn_create_pool", default="➕ Create Pool"), type="primary", width="stretch"):
                    _open_add_pool_dialog(pool_repo, tag_repo)

            df_all_pools = pool_repo.get_all_pools()
            if df_all_pools.empty:
                st.info(t("settings.no_pools_registered", default="No resource pools registered yet. Click 'Create Pool' to add one."))
            else:
                pool_id_map = {int(p.pool_id): p for p in all_pool_details}
                pool_options = df_all_pools["id"].tolist()
                target_pool_id = st.session_state.pop("target_resource_pool_id", None)
                if target_pool_id is not None and int(target_pool_id) in pool_options:
                    st.session_state["sb_selected_resource_pool"] = int(target_pool_id)

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

                details = load_pool_capacities(pool_repo.db_path, details=True, pool_ids=[selected_pool_id])
                current_detail = details[0] if details else None
                if current_detail:
                    # Pool Details & Action Row
                    c_info, c_actions = st.columns([4, 1])
                    with c_info:
                        st.markdown(f"### 🏊 **{current_detail.pool_name}** `[Pool #{current_detail.pool_id}]`")
                        pool_obj = pool_repo.get_pool_by_id(selected_pool_id)
                        if pool_obj and pool_obj.description:
                            st.caption(f"📝 {pool_obj.description}")
                        pool_tags = tag_repo.get_resource_pool_tags(selected_pool_id)
                        if not pool_tags.empty:
                            tag_text = " ".join(
                                f"`{row['tag_name']}`"
                                for _, row in pool_tags.iterrows()
                            )
                            st.markdown(f"🏷️ {tag_text}")
                    with c_actions:
                        c_edit, c_del = st.columns(2)
                        if c_edit.button("✏️", key=f"btn_edit_pool_{selected_pool_id}", help="Edit pool details"):
                            _open_edit_pool_dialog(pool_repo, tag_repo, selected_pool_id)
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
                        st.dataframe(pd.DataFrame(dedup_table_data), width="stretch", hide_index=True)

                    st.divider()

                    # Sub-section 3: Assignments on Projects & Tasks
                    st.write(f"#### 📁 / 📋 {t('settings.assignments_section_title', default='Active Allocations on Projects & Tasks')}")
                    _render_pool_assignments_table(current_detail.assignments, selected_pool_id, pool_repo)
