"""Confirmed mapping removal and source-specific capacity exception actions."""

import streamlit as st

from app.application.services.organization import OrganizationService
from app.application.services.resource_pools import ResourcePoolService
from app.application.services.pool_capacity_exceptions import PoolExceptionBreakdown
from app.presentation.components.action_table import action_table
from app.presentation.components.dialog import dialog
from app.presentation.components.resource_pool_dialogs import pool_errors, require_change
from app.presentation.components.organization_dialogs import _open_edit_employee_dialog
from app.presentation.components.organization_frames import functions_frame
from app.application.services.pool_restoration import PoolRestoreWarning


@dialog('Pool cannot be restored')
def restoration_blocked(warning: PoolRestoreWarning) -> None:
    """Explain the rejected transaction without offering an unsafe override."""
    st.error(f'{warning.pool_name} remains deleted because restoration would overallocate resources.')
    for reason in warning.reasons:
        st.write(reason)
    st.caption('Reduce the conflicting mappings in the active pools before trying again.')
    if st.button('Close', key='close_pool_restoration_warning'):
        st.rerun()


@dialog('Unmap resource from pool')
@pool_errors
def confirm_unmap(service: ResourcePoolService, pool_id: int, resource_type: str, resource_id: int, name: str) -> None:
    """Name every source mapping and affected employee before confirmation."""
    catalog = service.mapping_catalog()
    employee = next((item for item in catalog.sources.employees if item.employee_id == resource_id), None)
    functions = {row.function_id for row in employee.assignments()} if resource_type == 'employee' and employee else {resource_id}
    team_names = {team.team_id: team.team_name for team in catalog.sources.teams}
    function_names = {item.function_id: item.name for item in catalog.sources.functions}
    mappings = [row for row in catalog.sources.mappings if row.pool_id == pool_id and (
        (row.target_type == resource_type and row.target_id == resource_id)
        or (resource_type == 'employee' and row.target_type == 'function' and row.target_id in functions)
        or (resource_type == 'employee' and row.target_type == 'team'
            and functions.intersection(catalog.sources.team_functions.get(row.target_id, []))))]
    labels = {row.id: f'{row.target_type.title()}: ' + (
        team_names.get(row.target_id, str(row.target_id)) if row.target_type == 'team' else
        function_names.get(row.target_id, str(row.target_id)) if row.target_type == 'function' else name)
        + f' ({row.allocation_pct:g}%)' for row in mappings}
    pool_name = next((pool.name for pool in catalog.pools if pool.id == pool_id), str(pool_id))
    st.write(f'Remove mapping sources for {name} from pool {pool_name}.')
    chosen = st.multiselect('Mappings to remove', list(labels),
        default=list(labels),
        format_func=labels.get)
    for row in mappings:
        if row.id in chosen and row.target_type in {'team', 'function'}:
            ids = set(catalog.sources.team_functions.get(row.target_id, [])) if row.target_type == 'team' else {row.target_id}
            affected = [f'{person.firstname} {person.lastname}' for person in catalog.sources.employees
                        if ids.intersection(item.function_id for item in person.assignments())]
            st.warning(f'Removing {labels[row.id]} also removes its contribution for: ' + ', '.join(affected))
    if st.button('Confirm unmap', type='primary', disabled=not chosen):
        service.remove_pool_mappings(pool_id, chosen)
        st.toast('Resource unmapped.')
        st.rerun()
    if st.button('Cancel'):
        st.rerun()


@dialog('Delete pool capacity exception')
@pool_errors
def confirm_delete_exception(service: ResourcePoolService, item: PoolExceptionBreakdown) -> None:
    """Confirm removal of one pool-owned exception; employee exceptions stay separate."""
    st.write(f'Delete the exception for {item.pool_name}, from {item.start_date} to {item.end_date}?')
    if st.button('Delete exception', type='primary'):
        require_change(service.delete_capacity_exception(item.exception_id))
        st.toast('Pool capacity exception deleted.')
        st.rerun()
    if st.button('Cancel'):
        st.rerun()


def exception_actions(items: list[PoolExceptionBreakdown], pools: ResourcePoolService,
                      organization: OrganizationService) -> None:
    """Render source-specific row buttons without exposing invalid actions."""
    rows = [{'id': index, 'Pool': item.pool_name, 'Source': item.source, 'Resource': item.resource_name,
        'Mapped via': item.mapping_source, 'Date start': item.start_date, 'Date stop': item.end_date,
        'FTE reduction': item.reduction_fte, 'Employee availability (%)': item.occupation_percentage,
        'Reason': item.reason, 'accessible_name': item.resource_name,
        'allowed_actions': ['delete'] if item.source == 'Pool' else ['edit']}
        for index, item in enumerate(items)]
    columns = [(key, key) for key in ('Pool', 'Source', 'Resource', 'Mapped via', 'Date start', 'Date stop',
                                     'FTE reduction', 'Employee availability (%)', 'Reason')]
    event = action_table(rows, columns, {'delete': 'Delete', 'edit': 'Edit employee'}, key='pool_exception_actions')
    if event:
        item = items[event['id']]
        if event['action'] == 'delete':
            confirm_delete_exception(pools, item)
        else:
            _open_edit_employee_dialog(organization, item.employee_id, functions_frame(organization.get_all_functions()))
