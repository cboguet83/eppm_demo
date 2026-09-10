"""Resource-pool controls using injected application services."""

from collections.abc import Callable
from functools import wraps

import pandas as pd
import streamlit as st

from app.presentation.components.dialog import dialog

from app.application.exceptions import OrganizationStorageError, ResourcePoolStorageError
from app.application.services.resource_pools import ResourcePoolService
from app.domain.resources.models import (
    CapacityAssignment,
    PoolMapping,
    ResourcePool,
    ResourcePoolGroup,
)
from app.domain.resources.rules import (
    validate_pool_name,
    validate_capacity_fte,
    validate_allocation_pct,
)
from app.presentation.components.resource_pool_frames import (
    pools_frame,
    groups_frame,
    members_frame,
    tags_frame,
    tag_choices_frame,
)
from app.presentation.i18n import t


def pool_errors[**P](render: Callable[P, None]) -> Callable[P, None]:
    """Display safe application errors on page and dialog reruns."""

    @wraps(render)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            render(*args, **kwargs)
        except (ValueError, ResourcePoolStorageError, OrganizationStorageError) as exc:
            st.error(str(exc))

    return guarded


def require_change(changed: bool) -> None:
    """Prevent a concurrent deletion from being reported as a successful save."""
    if not changed:
        raise ValueError("This record no longer exists. Please refresh and try again.")


@dialog(t("settings.dialog_add_pool", default="➕ Create Resource Pool"))
@pool_errors
def _open_add_pool_dialog(service: ResourcePoolService) -> None:
    """Modal dialog to create a new resource pool."""
    new_name = st.text_input(
        t("settings.field_pool_name", default="Resource Pool Name *"),
        placeholder="e.g. Core Engineering Pool",
    )
    new_desc = st.text_area(
        t("settings.field_pool_desc", default="Description"),
        placeholder="Purpose and specialty of this pool...",
    )
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
    df_tags = tag_choices_frame(service.get_tag_choices())
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
    if col_save.button(
        t("settings.btn_save", default="💾 Save Pool"), type="primary", width="stretch"
    ):
        validate_pool_name(new_name)
        validate_capacity_fte(float(new_capacity))
        p_id = service.create_pool(
            ResourcePool(
                name=new_name.strip(),
                description=new_desc.strip(),
                capacity_fte=float(new_capacity),
            ),
            tag_ids=selected_tag_ids,
        )
        st.toast(f"Resource Pool '{new_name}' created (ID: {p_id})!", icon="✅")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@dialog(t("settings.dialog_edit_pool", default="✏️ Edit Resource Pool"))
@pool_errors
def _open_edit_pool_dialog(service: ResourcePoolService, pool_id: int) -> None:
    """Modal dialog to edit an existing resource pool."""
    pool = service.get_pool_by_id(pool_id)
    if not pool:
        st.error("Resource pool not found.")
        return
    edit_name = st.text_input(
        t("settings.field_pool_name", default="Resource Pool Name *"), value=pool.name
    )
    edit_desc = st.text_area(
        t("settings.field_pool_desc", default="Description"), value=pool.description
    )
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
    df_tags = tag_choices_frame(service.get_tag_choices())
    tag_labels = {
        int(row["id"]): (
            f"{row['tag_group_name']} · {row['tag']}"
            if pd.notna(row.get("tag_group_name"))
            else str(row["tag"])
        )
        for _, row in df_tags.iterrows()
    }
    existing_pool_tags = tags_frame(service.get_pool_tags(pool_id))
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
    if col_save.button(
        t("settings.btn_save_changes", default="💾 Save Changes"), type="primary", width="stretch"
    ):
        validate_pool_name(edit_name)
        validate_capacity_fte(float(edit_capacity))
        require_change(
            service.update_pool(
                ResourcePool(
                    id=pool_id,
                    name=edit_name.strip(),
                    description=edit_desc.strip(),
                    capacity_fte=float(edit_capacity),
                ),
                tag_ids=selected_tag_ids,
            )
        )
        st.toast("Resource Pool updated successfully!", icon="✏️")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@dialog(t("settings.delete_confirm_title", default="🗑️ Confirm Deletion"))
@pool_errors
def _open_delete_pool_dialog(service: ResourcePoolService, pool_id: int, pool_name: str) -> None:
    """Modal dialog to confirm deletion of a resource pool."""
    st.warning(
        f"⚠️ Are you sure you want to delete Resource Pool **{pool_name}** (ID: #{pool_id})?"
    )
    st.caption(
        "All mappings and project/task assignments linked to this pool will also be deleted."
    )
    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(
        t("settings.btn_confirm_delete", default="🗑️ Yes, Delete"), type="primary", width="stretch"
    ):
        require_change(service.delete_pool(pool_id))
        st.toast(f"Resource Pool '{pool_name}' deleted.", icon="🗑️")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


def _pool_group_option_maps(service: ResourcePoolService) -> tuple[dict[int, str], dict[int, str]]:
    """Build current resource-pool and group labels for membership controls."""
    pools = pools_frame(service.get_all_pools())
    groups = groups_frame(service.get_all_pool_groups())
    pool_labels = {int(row["id"]): str(row["name"]) for _, row in pools.iterrows()}
    group_labels = {int(row["id"]): str(row["name"]) for _, row in groups.iterrows()}
    return (pool_labels, group_labels)


@dialog("➕ Create pool group")
@pool_errors
def _open_add_pool_group_dialog(service: ResourcePoolService) -> None:
    """Create a recursive group and its direct members."""
    pool_labels, group_labels = _pool_group_option_maps(service)
    name = st.text_input("Group name *", placeholder="e.g. Digital delivery")
    description = st.text_area("Description", placeholder="Purpose of this pool group")
    selected_pool_ids = st.multiselect(
        "Direct pools", options=list(pool_labels), format_func=lambda pool_id: pool_labels[pool_id]
    )
    selected_group_ids = st.multiselect(
        "Child groups",
        options=list(group_labels),
        format_func=lambda group_id: group_labels[group_id],
        help="Child groups can contain pools or more child groups.",
    )
    save_col, cancel_col = st.columns(2)
    if save_col.button("💾 Save group", type="primary", width="stretch"):
        service.create_pool_group(
            ResourcePoolGroup(name=name, description=description),
            pool_ids=selected_pool_ids,
            child_group_ids=selected_group_ids,
        )
        st.toast(f"Pool group '{name}' created.", icon="✅")
        st.rerun()
    if cancel_col.button("Cancel", width="stretch"):
        st.rerun()


@dialog("✏️ Edit pool group")
@pool_errors
def _open_edit_pool_group_dialog(service: ResourcePoolService, group_id: int) -> None:
    """Edit a recursive group while excluding child choices that form cycles."""
    group = service.get_pool_group_by_id(group_id)
    if group is None:
        st.error("Pool group not found.")
        return
    pool_labels, group_labels = _pool_group_option_maps(service)
    current_pool_ids, current_child_ids = service.get_group_direct_member_ids(group_id)
    allowed_ids = service.get_allowed_child_group_ids(group_id)
    safe_group_labels = {
        candidate_id: label
        for candidate_id, label in group_labels.items()
        if candidate_id in allowed_ids
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
        require_change(
            service.update_pool_group(
                ResourcePoolGroup(id=group_id, name=name, description=description),
                pool_ids=selected_pool_ids,
                child_group_ids=selected_group_ids,
            )
        )
        st.toast("Pool group updated.", icon="✅")
        st.rerun()
    if cancel_col.button("Cancel", width="stretch"):
        st.rerun()


@dialog("🗑️ Delete pool group")
@pool_errors
def _open_delete_pool_group_dialog(
    service: ResourcePoolService, group_id: int, group_name: str
) -> None:
    """Confirm deletion of a pool group without deleting its member pools."""
    st.warning(f"Delete pool group **{group_name}**?")
    st.caption("Member pools and child groups are retained; only group memberships are removed.")
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button("🗑️ Delete group", type="primary", width="stretch"):
        require_change(service.delete_pool_group(group_id))
        st.toast(f"Pool group '{group_name}' deleted.", icon="🗑️")
        st.rerun()
    if cancel_col.button("Cancel", width="stretch"):
        st.rerun()


def _render_pool_groups_management(service: ResourcePoolService) -> None:
    """Render creation, editing, and recursive membership inspection for pool groups."""
    expander = st.expander("🗂️ Recursive pool groups", expanded=False, on_change="rerun")
    if not expander.open:
        return
    with expander:
        title_col, create_col = st.columns([4, 1])
        title_col.caption(
            "Groups may contain resource pools or other groups. Recursive membership is deduplicated and loop-safe."
        )
        if create_col.button("➕ New group", width="stretch"):
            _open_add_pool_group_dialog(service)
        groups = groups_frame(service.get_all_pool_groups())
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
        group_labels = {int(row["id"]): str(row["name"]) for _, row in groups.iterrows()}
        selected_group_id = st.selectbox(
            "Inspect group",
            options=list(group_labels),
            format_func=lambda group_id: group_labels[group_id],
            key="selected_resource_pool_group",
        )
        edit_col, delete_col, _ = st.columns([1, 1, 3])
        if edit_col.button("✏️ Edit", width="stretch"):
            _open_edit_pool_group_dialog(service, selected_group_id)
        if delete_col.button("🗑️ Delete", width="stretch"):
            _open_delete_pool_group_dialog(
                service, selected_group_id, group_labels[selected_group_id]
            )
        direct_members = members_frame(service.get_group_members(selected_group_id))
        all_pool_ids = service.get_group_descendant_pool_ids(selected_group_id)
        all_pools = pools_frame(service.get_all_pools())
        pool_names = {int(row["id"]): str(row["name"]) for _, row in all_pools.iterrows()}
        direct_labels = (
            [
                f"{('Pool' if row['member_type'] == 'pool' else 'Group')}: {row['member_name']}"
                for _, row in direct_members.iterrows()
            ]
            if not direct_members.empty
            else []
        )
        st.caption("Direct members: " + (" · ".join(direct_labels) if direct_labels else "None"))
        st.write(
            "Resolved pools:",
            ", ".join((pool_names.get(pool_id, f"Pool #{pool_id}") for pool_id in all_pool_ids))
            or "None",
        )


@dialog(t("settings.dialog_add_mapping", default="➕ Assign Team or Employee to Pool"))
@pool_errors
def _open_add_pool_mapping_dialog(
    service: ResourcePoolService, pool_id: int, df_teams: pd.DataFrame, df_employees: pd.DataFrame
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
            int(
                row["employee_id"]
            ): f"{str(row['firstname']).strip()} {str(row['lastname']).strip()}".strip()
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
    if col_save.button(
        t("settings.btn_save_mapping", default="💾 Save Mapping"), type="primary", width="stretch"
    ):
        validate_allocation_pct(float(alloc_pct))
        service.create_mapping(
            PoolMapping(
                pool_id=pool_id,
                target_type=map_type,
                target_id=int(target_id),
                allocation_pct=float(alloc_pct),
            )
        )
        st.toast("Mapping added / updated successfully!", icon="✅")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


def _render_pool_assignments_table(
    assignments: list[CapacityAssignment],
    selected_pool_id: int,
    service: ResourcePoolService,
    planning_page: str,
    *,
    allow_unassign: bool = True,
) -> None:
    """Show navigation and optional unassignment actions on each allocation row."""
    from app.presentation.components.action_table import action_table

    if not assignments:
        st.info(t("settings.no_assignments_for_pool", default="This pool is not currently assigned to any project or task."))
        return
    rows = [{
        "id": int(row["id"]), "project": row["project_name"],
        "task": row["task_name"] if row["task_id"] else "Project level",
        "fte": f"{row['fte_assigned']:.2f}",
        "period": f"{row['start_date']} → {row['end_date']}",
        "notes": row.get("notes") or "—", "accessible_name": row["project_name"],
    } for row in assignments]
    event = action_table(rows, [
        ("id", "ID"), ("project", t("settings.col_project", default="Project")),
        ("task", t("settings.col_task", default="Task / Step")),
        ("fte", "Assigned FTE"), ("period", "Effective period"), ("notes", "Notes"),
    ], {"open": t("settings.go_to", default="Go to"), **({"unassign": "Unassign"} if allow_unassign else {})},
        key=f"pool_assignments_{selected_pool_id}")
    if event is None:
        return
    chosen = next(row for row in assignments if row["id"] == event["id"])
    if event["action"] == "unassign":
        _confirm_unassign(service, selected_pool_id, int(chosen["id"]), str(chosen["project_name"]))
    elif event["action"] == "open":
        st.session_state.pop("active_resource_pool_filter", None)
        st.session_state.pop("pending_resource_pool_filter", None)
        st.session_state.pop("target_planning_task_id", None)
        st.session_state["target_planning_project_id"] = int(chosen["project_id"])
        st.session_state["ms_multi_projects"] = [int(chosen["project_id"])]
        if chosen.get("task_id"):
            st.session_state["target_planning_task_id"] = int(chosen["task_id"])
        st.session_state["nav_redirect"] = planning_page
        st.rerun()


@dialog("Confirm unassignment")
@pool_errors
def _confirm_unassign(
    service: ResourcePoolService, pool_id: int, assignment_id: int, project_name: str,
) -> None:
    """Require explicit confirmation before removing the selected allocation."""
    st.write(f"Unassign allocation #{assignment_id} from {project_name}?")
    with st.container(horizontal=True):
        if st.button("Confirm unassign", type="primary", key=f"confirm_unassign_{assignment_id}"):
            current = service.get_assignment_by_id(assignment_id)
            if current is None or current.pool_id != pool_id:
                st.error("The allocation no longer exists in this pool.")
                return
            require_change(service.delete_assignment(assignment_id))
            st.toast("Allocation removed.")
            st.rerun()
        if st.button("Cancel", key=f"cancel_unassign_{assignment_id}"):
            st.rerun()
