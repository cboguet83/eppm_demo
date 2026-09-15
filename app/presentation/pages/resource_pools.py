"""Resource-pool settings backed by typed catalog and capacity use cases."""

import streamlit as st
import pandas as pd

from app.application.services.organization import OrganizationService
from app.application.services.resource_pools import ResourcePoolService
from app.application.services.pool_capacity import PoolCapacityService
from app.domain.resources.hierarchy import PoolHierarchy
from app.domain.projects.project import PROJECT_STATUSES
from app.domain.resources.models import PoolCapacityDetail
from app.presentation.components.resource_pool_dialogs import (
    pool_errors,
    _open_add_pool_dialog,
    _open_edit_pool_dialog,
    _open_add_pool_mapping_dialog,
    _render_pool_assignments_table,
)
from app.presentation.components.resource_pool_tree import resource_pool_tree
from app.presentation.components.organization_frames import teams_frame, employees_frame
from app.presentation.i18n import get_current_locale, t
from app.domain.resources.overallocation import overallocation_periods


@pool_errors
def render_resource_pools(
    service: ResourcePoolService,
    capacity: PoolCapacityService,
    organization: OrganizationService,
    planning_page: str,
) -> None:
    """Render the tree, overassigned periods and selected pool resource details."""
    pool_records = service.get_all_pools()
    hierarchy = PoolHierarchy(pool_records)
    statuses = st.multiselect('Project statuses included in demand', PROJECT_STATUSES,
                              default=['In Progress'], key='pool_demand_statuses')
    project_ids = service.project_ids_for_statuses(statuses)
    all_pool_details = capacity.get_details(list(hierarchy.pools), project_ids=project_ids)
    mappings = service.get_all_mappings()
    mapping_types: dict[int, set[str]] = {}
    for mapping in mappings:
        mapping_types.setdefault(mapping.pool_id, set()).add(mapping.target_type)
    current_capacities = capacity.current_capacities(hierarchy, all_pool_details,
                                                    set(mapping_types))
    leaf_details = [row for row in all_pool_details if not hierarchy.children.get(row.pool_id)]
    total_pools = len(all_pool_details)
    total_portfolio_capacity = sum((p.total_capacity_fte for p in leaf_details))
    total_assigned_capacity = sum((p.assigned_capacity_fte for p in leaf_details))
    peak_portfolio_assigned = capacity.future_peak_demand(leaf_details)
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
        "Future Peak Demand",
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
    if not pool_records:
        event = resource_pool_tree(hierarchy, {}, 0)
        if event and event['action'] == 'create_root':
            _open_add_pool_dialog(service)
    else:
        target_pool_id = st.session_state.pop("target_resource_pool_id", None)
        selected_pool_id = target_pool_id or st.session_state.get("sb_selected_resource_pool")
        if selected_pool_id not in hierarchy.pools:
            selected_pool_id = next(identity for identity, pool in hierarchy.pools.items()
                                    if pool.parent_pool_id is None)
        st.session_state["sb_selected_resource_pool"] = selected_pool_id
        event = resource_pool_tree(hierarchy,
            {row.pool_id: row.total_capacity_fte for row in all_pool_details}, selected_pool_id,
            assigned_capacities=current_capacities,
            peak_demands={row.pool_id: capacity.future_peak_demand([row]) for row in all_pool_details},
            peak_capacities=capacity.peak_date_capacities(hierarchy, all_pool_details, set(mapping_types)),
            mapping_types=mapping_types,
            pool_types={row.id: row.label(get_current_locale()) for row in service.get_all_pool_types()},
            hierarchy_types={row.id: row.label(get_current_locale()) for row in service.get_all_hierarchy_types()},
            tags=service.get_tags_by_pools(list(hierarchy.pools)))
        if event and event['action'] == 'create_root':
            _open_add_pool_dialog(service)
        elif event:
            selected_pool_id = event['id']
            st.session_state["sb_selected_resource_pool"] = selected_pool_id
            if event['action'] == 'select':
                st.rerun()
            elif event['action'] == 'edit':
                _open_edit_pool_dialog(service, selected_pool_id)
            elif event['action'] == 'gantt':
                _open_pool_consuming_projects(hierarchy, selected_pool_id, all_pool_details, statuses, planning_page)
            elif event['action'] == 'map':
                hierarchy.require_leaf(selected_pool_id)
                _open_add_pool_mapping_dialog(service, selected_pool_id,
                    teams_frame(organization.get_all_teams()), employees_frame(organization.get_all_employees()))
            else:
                warning = service.parent_pool_warning(selected_pool_id)
                if warning:
                    st.warning(warning)
                else:
                    _open_add_pool_dialog(service, selected_pool_id)
        current_detail = next((row for row in all_pool_details if row.pool_id == selected_pool_id), None)
        if current_detail:
            leaf_details = (
                [row for row in all_pool_details if row.pool_id in hierarchy.descendants(selected_pool_id, leaves_only=True)]
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
            st.markdown('#### Pool overallocation')
            periods = overallocation_periods(leaf_details)
            if periods:
                st.caption('FTE is the excess above available capacity. Dates are inclusive.')
                st.dataframe(pd.DataFrame([
                    {'Pool name': period.pool_name, 'Date start': period.start_date,
                     'Date stop': period.stop_date, 'FTE': period.fte}
                    for period in periods
                ]), hide_index=True, width='stretch', column_config={
                    'FTE': st.column_config.NumberColumn('FTE', format='%.3f'),
                })
            else:
                st.caption(f"No overassigned periods for {current_detail.pool_name}.")
            st.markdown("#### Active Allocations on Projects & Tasks")
            for detail in leaf_details:
                if len(leaf_details) > 1:
                    st.markdown(f"**{detail.pool_name}**")
                _render_pool_assignments_table(detail.assignments, detail.pool_id, service, planning_page)


def _open_pool_consuming_projects(hierarchy: PoolHierarchy, pool_id: int,
                                  details: list[PoolCapacityDetail], statuses: list[str],
                                  planning_page: str) -> None:
    """Queue the Gantt's existing pool filter for status-scoped consuming projects."""
    pool_ids = hierarchy.descendants(pool_id, leaves_only=True)
    projects = sorted({row['project_id'] for detail in details if detail.pool_id in pool_ids
                       for row in detail.assignments if row['fte_assigned'] > 0})
    st.session_state['planning_statuses'] = list(statuses)
    for key in ('target_planning_project_id', 'target_planning_task_id', 'pending_project_context_filter'):
        st.session_state.pop(key, None)
    st.session_state['active_resource_pool_filter'] = {
        'pool_id': pool_id, 'group_id': pool_id if hierarchy.children.get(pool_id) else None,
        'pool_ids': pool_ids, 'pool_name': hierarchy.pools[pool_id].name,
        'start_date': '0001-01-01', 'end_date': '9999-12-31', 'clear_other_filters': True,
        'project_ids': projects, 'count': len(projects),
    }
    st.session_state['pending_resource_pool_filter'] = {'clear_other': True, 'target_pids': projects}
    st.session_state['nav_redirect'] = planning_page
    st.rerun()
