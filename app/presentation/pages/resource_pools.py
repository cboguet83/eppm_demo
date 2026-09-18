"""Resource-pool settings backed by typed catalog and capacity use cases."""

import streamlit as st
import pandas as pd

from app.application.services.organization import OrganizationService
from app.application.services.resource_pools import ResourcePoolService
from app.application.services.pool_capacity import PoolCapacityService
from app.application.services.pool_capacity_exceptions import capacity_exception_breakdown, PoolExceptionBreakdown
from app.domain.resources.hierarchy import PoolHierarchy
from app.domain.resources.models import PoolCapacityDetail
from app.presentation.components.resource_pool_dialogs import (
    pool_errors,
    _open_add_pool_dialog,
    _open_edit_pool_dialog,
    _open_delete_pool_dialog,
    _open_add_pool_mapping_dialog,
    _render_pool_assignments_table,
)
from app.presentation.components.resource_pool_tree import resource_pool_tree
from app.presentation.components.resource_pool_csv import pool_csv_controls
from app.presentation.components.organization_frames import teams_frame, employees_frame
from app.presentation.i18n import get_current_locale, t
from app.domain.resources.overallocation import overallocation_periods
from app.presentation.components.action_table import TableAction
from app.application.services.pool_restoration import PoolRestorationError


@pool_errors
def render_resource_pools(
    service: ResourcePoolService,
    capacity: PoolCapacityService,
    organization: OrganizationService,
    planning_page: str,
) -> None:
    """Render the tree, overassigned periods and selected pool resource details."""
    statuses = ['In Progress']
    show_deleted = st.checkbox('Show deleted pools', value=False, key='pool_show_deleted')
    pool_records = service.get_all_pools(include_deleted=show_deleted)
    pool_csv_controls(service, show_deleted=show_deleted)
    hierarchy = PoolHierarchy(pool_records)
    active_hierarchy = PoolHierarchy([pool for pool in pool_records if not pool.deleted_flag])
    project_ids = service.project_ids_for_statuses(statuses)
    leaf_ids = [identity for identity in active_hierarchy.pools if not active_hierarchy.children.get(identity)]
    all_pool_details = capacity.get_details(leaf_ids, project_ids=project_ids)
    mappings = service.get_all_mappings()
    catalog = service.mapping_catalog()
    allocations = catalog.allocations()
    functions = {row.function_id: row.name for row in catalog.sources.functions if not row.deleted_flag}
    employee_functions = {person.employee_id: ', '.join(
        f'{functions[row.function_id]} ({row.allocation_pct:.0f}%)' for row in person.assignments()
        if row.function_id in functions) for person in catalog.sources.employees}
    allocation_details = []
    for resource in sorted(allocations.overallocated):
        description = allocations.warning(resource)
        if resource[0] == 'employee' and employee_functions.get(resource[1]):
            description += ' Functions: ' + employee_functions[resource[1]] + '.'
        allocation_details.append(description)
    mapping_types: dict[int, set[str]] = {}
    for mapping in mappings:
        mapping_types.setdefault(mapping.pool_id, set()).add(mapping.target_type)
    current_capacities = capacity.current_capacities(active_hierarchy, all_pool_details,
                                                    set(mapping_types), include_containers=False)
    total_pools = len(leaf_ids)
    overassigned_pools_count = sum(1 for pool in all_pool_details if pool.is_overassigned)
    unassigned_pools_count = sum(not (mapping_types.get(identity, set()) & {'employee', 'team'})
                                 for identity in leaf_ids)
    exceptions = capacity_exception_breakdown(all_pool_details, service.capacity_exceptions_many(leaf_ids),
                                             organization.get_employee_calendar_exceptions())
    future_exception_ids = capacity.future_exception_pool_ids(exceptions)
    kpi1, kpi3, kpi2, kpi4, kpi5 = st.columns(5)
    overallocated = len(allocations.overallocated)
    with kpi5.container(key='overallocated_resources'):
        st.metric('Overallocated teams / employees', f'⚠ {overallocated}' if overallocated else '0',
                help='Unique teams and employees allocated above 100% across active pools. '
                     'Employee totals include team mappings, deduplicated within each pool. Deleted pools are excluded.'
                     + ('\n\n' + '\n\n'.join(allocation_details) if allocation_details else ''))
    if overallocated:
        st.html('<style>.st-key-overallocated_resources [data-testid="stMetricValue"] {color:#c41039;}</style>')
    kpi1.metric(t("settings.kpi_total_pools", default="Total Pools"), total_pools)
    kpi3.metric('Pools with no assignment', unassigned_pools_count,
                help='Active leaf pools with no employee or team mapped. Containers and deleted pools are excluded.')
    kpi4.metric('Pools with future capacity exceptions', len(future_exception_ids),
                help='Active leaf pools with an applicable exception ending today or later. Mapped pools use employee exceptions; unmapped pools use pool exceptions.')
    if overassigned_pools_count > 0:
        kpi2.metric(
            t("settings.kpi_overassigned_pools", default="Overassigned Pools"),
            str(overassigned_pools_count),
            delta=f"+{overassigned_pools_count} Alert",
            delta_color="inverse",
            delta_arrow="off",
        )
    else:
        kpi2.metric(t("settings.kpi_overassigned_pools", default="Overassigned Pools"), "0")
    st.divider()
    st.caption("Only active leaf pools have capacity and demand values. Summary counts exclude containers and deleted pools.")
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
            peak_capacities=capacity.peak_date_capacities(active_hierarchy, all_pool_details, set(mapping_types)),
            mapping_types=mapping_types,
            future_exception_ids=future_exception_ids,
            resource_warnings=allocations.pool_warnings(),
            overallocated_employee_pool_ids={pool for key in allocations.overallocated if key[0] == 'employee'
                                             for pool, percentage in allocations.usage[key].items() if percentage > 0},
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
            elif event['action'] == 'delete':
                _open_delete_pool_dialog(service, selected_pool_id, hierarchy.pools[selected_pool_id].name)
            elif event['action'] == 'undelete':
                try:
                    if service.undelete_pool(selected_pool_id):
                        st.toast('Resource pool restored.')
                        st.rerun()
                except PoolRestorationError as error:
                    from app.presentation.components.pool_detail_actions import restoration_blocked
                    restoration_blocked(error.warning)
            elif event['action'] == 'edit':
                _open_edit_pool_dialog(service, selected_pool_id)
            elif event['action'] == 'gantt':
                _open_pool_consuming_projects(active_hierarchy, selected_pool_id, all_pool_details, statuses, planning_page)
            elif event['action'] == 'map':
                active_hierarchy.require_leaf(selected_pool_id)
                _open_add_pool_mapping_dialog(service, selected_pool_id,
                    teams_frame(organization.get_all_teams()), employees_frame(organization.get_all_employees()))
            elif event['action'] == 'create':
                warning = service.parent_pool_warning(selected_pool_id)
                if warning:
                    st.warning(warning)
                else:
                    _open_add_pool_dialog(service, selected_pool_id)
        if selected_pool_id in active_hierarchy.pools:
            selected_leaves = active_hierarchy.descendants(selected_pool_id, leaves_only=True)
            leaf_details = [row for row in all_pool_details if row.pool_id in selected_leaves]
            _render_exception_breakdown([item for item in exceptions if item.pool_id in selected_leaves], service, organization)
            st.markdown("####  Mapped  Capacity Breakdown")
            st.caption("Employees mapped directly or through several teams are counted once within each pool.")
            contributions = [
                {"Pool": detail.pool_name, "Resource": ('⚠ ' if (item.resource_type, item.resource_id)
                    in allocations.overallocated else '') + item.resource_name,
                 "Resource type": item.resource_type.title(), "Function": item.function_name,
                 "Nominal FTE": item.nominal_fte, "Effective %": f'{item.effective_allocation_pct:.0f}',
                 "Effective FTE": item.effective_fte, "Source": item.source_name,
                 "Deduplication": "Direct override" if item.is_deduplicated else "Standard"}
                for detail in leaf_details for item in detail.contributing_resources
            ]
            if contributions:
                warnings = [allocations.warning((item.resource_type, item.resource_id))
                            if (item.resource_type, item.resource_id) in allocations.overallocated else ''
                            for detail in leaf_details for item in detail.contributing_resources]
                event = _mapping_breakdown(contributions, warnings)
                if event:
                    from app.presentation.components.pool_detail_actions import confirm_unmap
                    sources = [(detail.pool_id, item) for detail in leaf_details for item in detail.contributing_resources]
                    owner, resource = sources[event['id']]
                    confirm_unmap(service, owner, resource.resource_type, resource.resource_id, resource.resource_name)
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
                st.caption(f"No overassigned periods for {hierarchy.pools[selected_pool_id].name}.")
            st.markdown("#### Active Allocations on Projects & Tasks")
            for detail in leaf_details:
                if len(leaf_details) > 1:
                    st.markdown(f"**{detail.pool_name}**")
                _render_pool_assignments_table(detail.assignments, detail.pool_id, service, planning_page)


def _mapping_breakdown(rows: list[dict], warnings: list[str]) -> TableAction | None:
    """Render allocation warnings and an Unmap action on each resource row."""
    from app.presentation.components.action_table import action_table
    columns = [(key, key) for key in rows[0]]
    payload = [row | {'id': index, 'accessible_name': row['Resource'],
                     'tooltips': {'Resource': warning} if warning else {}}
               for index, (row, warning) in enumerate(zip(rows, warnings))]
    return action_table(payload, columns, {'unmap': 'Unmap'}, key='pool_mapping_breakdown')


def _render_exception_breakdown(exceptions: list[PoolExceptionBreakdown], service: ResourcePoolService,
                                organization: OrganizationService) -> None:
    """Show all effective exception periods for the selected leaf or subtree."""
    st.markdown('#### Pool capacity exception breakdown')
    if not exceptions:
        st.caption('No applicable capacity exceptions for this pool.')
        return
    st.caption('All periods are shown, including past exceptions. Employee exceptions replace pool exceptions when resources are mapped. '
               'FTE reduction includes the mapping allocation; a negative value increases capacity.')
    from app.presentation.components.pool_detail_actions import exception_actions
    exception_actions(exceptions, service, organization)


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
