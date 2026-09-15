"""Resource-pool settings backed by typed catalog and capacity use cases."""

import streamlit as st
import pandas as pd

from app.application.services.organization import OrganizationService
from app.application.services.resource_pools import ResourcePoolService
from app.application.services.pool_capacity import PoolCapacityService
from app.domain.resources.hierarchy import PoolHierarchy
from app.presentation.components.resource_pool_dialogs import (
    pool_errors,
    _open_add_pool_dialog,
    _open_edit_pool_dialog,
    _render_pool_assignments_table,
)
from app.presentation.components.resource_pool_tree import resource_pool_tree
from app.presentation.i18n import get_current_locale, t


@pool_errors
def render_resource_pools(
    service: ResourcePoolService,
    capacity: PoolCapacityService,
    organization: OrganizationService,
    planning_page: str,
) -> None:
    """Render the tree, overassigned periods and selected pool resource details."""
    all_pool_details = capacity.get_summaries()
    pool_records = service.get_all_pools()
    hierarchy = PoolHierarchy(pool_records)
    leaf_details = [row for row in all_pool_details if not hierarchy.children.get(row.pool_id)]
    total_pools = len(all_pool_details)
    total_portfolio_capacity = sum((p.total_capacity_fte for p in leaf_details))
    total_assigned_capacity = sum((p.assigned_capacity_fte for p in leaf_details))
    peak_portfolio_assigned = sum((p.peak_assigned_fte for p in leaf_details))
    overassigned_pools_count = sum((1 for p in leaf_details if p.is_overassigned))
    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric(t("settings.kpi_total_pools", default="Total Pools"), total_pools)
    kpi2.metric(
        t("settings.kpi_total_capacity", default="Defined Capacity"),
        f"{total_portfolio_capacity:.2f} FTE",
    )
    kpi3.metric(
        t("settings.kpi_assigned_capacity", default="Assigned Capacity"),
        f"{total_assigned_capacity:.2f} FTE",
    )
    kpi4.metric(
        t("settings.kpi_peak_demand", default="Peak Active Demand"),
        f"{peak_portfolio_assigned:.2f} FTE",
    )
    if overassigned_pools_count > 0:
        kpi5.metric(
            t("settings.kpi_overassigned_pools", default="Overassigned Pools"),
            str(overassigned_pools_count),
            delta=f"+{overassigned_pools_count} Alert",
            delta_color="inverse",
            delta_arrow="off",
        )
    else:
        kpi5.metric(t("settings.kpi_overassigned_pools", default="Overassigned Pools"), "0")
    st.divider()
    st.caption("Pools form a hierarchy. Only pools without children can be assigned; containers total their children’s capacity.")
    st.caption("Pools have a defined capacity (FTE) and can be assigned to projects and tasks.")
    st.caption("Employees defined in the system can be mapped to pools via their team memberships or directly, and their effective allocation is counted towards the pool’s assigned capacity.")
    _, col_add_btn = st.columns([4, 1])
    with col_add_btn:
        if st.button(
            t("settings.btn_create_pool", default="Create Pool"),
            type="primary",
            width="stretch",
        ):
            _open_add_pool_dialog(service)
    if not pool_records:
        st.info(
            t(
                "settings.no_pools_registered",
                default="No resource pools registered yet. Click 'Create Pool' to add one.",
            )
        )
    else:
        target_pool_id = st.session_state.pop("target_resource_pool_id", None)
        selected_pool_id = target_pool_id or st.session_state.get("sb_selected_resource_pool")
        if selected_pool_id not in hierarchy.pools:
            selected_pool_id = next(identity for identity, pool in hierarchy.pools.items()
                                    if pool.parent_pool_id is None)
        st.session_state["sb_selected_resource_pool"] = selected_pool_id
        event = resource_pool_tree(hierarchy,
            {row.pool_id: row.total_capacity_fte for row in all_pool_details}, selected_pool_id,
            assigned_capacities={row.pool_id: row.assigned_capacity_fte for row in all_pool_details},
            pool_types={row.id: row.label(get_current_locale()) for row in service.get_all_pool_types()},
            hierarchy_types={row.id: row.label(get_current_locale()) for row in service.get_all_hierarchy_types()},
            tags=service.get_tags_by_pools(list(hierarchy.pools)))
        if event:
            selected_pool_id = event['id']
            st.session_state["sb_selected_resource_pool"] = selected_pool_id
            if event['action'] == 'select':
                st.rerun()
            elif event['action'] == 'edit':
                _open_edit_pool_dialog(service, selected_pool_id)
            else:
                warning = service.parent_pool_warning(selected_pool_id)
                if warning:
                    st.warning(warning)
                else:
                    _open_add_pool_dialog(service, selected_pool_id)
        details = capacity.get_details([selected_pool_id])
        current_detail = details[0] if details else None
        if current_detail and current_detail.is_overassigned:
            st.error(
                f"**Overassigned periods - {current_detail.pool_name}**\n\n"
                + (', '.join(current_detail.overassignment_intervals) or 'Active overlapping assignments')
            )
        elif current_detail:
            st.caption(f"No overassigned periods for {current_detail.pool_name}.")
        if current_detail:
            leaf_details = (
                capacity.get_details(hierarchy.descendants(selected_pool_id, leaves_only=True))
                if hierarchy.children.get(selected_pool_id) else [current_detail]
            )
            st.markdown("####  Mapped  Capacity Breakdown")
            st.caption("Employees mapped directly or through several teams are counted once within each pool.")
            contributions = [
                {"Pool": detail.pool_name, "Resource": item.resource_name,
                 "Resource type": item.resource_type.title(), "Function": item.function_name,
                 "Nominal FTE": item.nominal_fte, "Effective %": item.effective_allocation_pct,
                 "Effective FTE": item.effective_fte, "Source": item.source_name,
                 "Deduplication": "Direct override" if item.is_deduplicated else "Standard"}
                for detail in leaf_details for item in detail.contributing_resources
            ]
            if contributions:
                st.dataframe(pd.DataFrame(contributions), hide_index=True, width="stretch")
            else:
                st.caption("No mapped resources contribute capacity to this pool.")
            st.markdown("#### Active Allocations on Projects & Tasks")
            for detail in leaf_details:
                if len(leaf_details) > 1:
                    st.markdown(f"**{detail.pool_name}**")
                _render_pool_assignments_table(detail.assignments, detail.pool_id, service, planning_page)
