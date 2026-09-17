"""Hierarchical team administration and employee-derived capacity details."""

import pandas as pd
import streamlit as st

from app.application.services.organization import OrganizationService
from app.application.services.team_capacity import TeamOverview
from app.presentation.components.organization_dialogs import (
    organization_errors, _open_add_team_dialog, _open_edit_team_dialog, _open_delete_team_dialog,
)
from app.presentation.components.organization_frames import functions_frame
from app.presentation.components.team_csv import team_csv_controls
from app.presentation.components.team_tree import team_tree
from app.presentation.i18n import get_current_locale


def _details(overview: TeamOverview, selected: int) -> None:
    detail = overview.capacities[selected]
    st.subheader('Team mapping breakdown')
    st.caption('Only explicitly mapped functions count. Employees are counted once; vacant functions contribute zero FTE. '
               'Parent teams and manager functions do not imply membership.')
    members = [{'Function': member.function_name, 'Employee': member.employee_name or 'Vacant',
                'Current FTE': member.current_fte} for member in detail.members]
    if members:
        st.dataframe(pd.DataFrame(members), hide_index=True, width='stretch')
    else:
        st.info('No active function mappings for this team.')
    st.subheader('Team capacity exceptions')
    st.caption('All employee exception periods are shown, including past exceptions. Dates are inclusive.')
    function_names = {member.employee_id: member.function_name for member in detail.members}
    periods = [{'Function': function_names[item.employee_id], 'Employee': f'{item.firstname} {item.lastname}',
                'Source': 'Employee', 'Date start': item.start_date, 'Date stop': item.end_date,
                'Employee FTE during exception': item.occupation_percentage / 100, 'Reason': item.reason}
               for item in detail.exceptions]
    if periods:
        st.dataframe(pd.DataFrame(periods), hide_index=True, width='stretch')
    else:
        st.info('No employee capacity exceptions for this team.')
    st.subheader('Team active allocations')
    allocations = [{'Pool': item['pool_name'], 'Allocation (%)': item['allocation_pct']}
                   for item in overview.pool_mappings if item['team_id'] == selected]
    if allocations:
        st.dataframe(pd.DataFrame(allocations), hide_index=True, width='stretch')
    else:
        st.info('This team is not mapped to an active resource pool.')


@organization_errors
def render_teams(service: OrganizationService) -> None:
    """Show live team counts, a filtered hierarchy and the selected team's details."""
    show_deleted = st.checkbox('Show deleted teams', value=False, key='team_show_deleted')
    team_csv_controls(service, show_deleted=show_deleted)
    overview = service.team_overview(include_deleted=show_deleted)
    teams = {team.team_id: team for team in overview.teams}
    active = [team for team in overview.teams if not team.deleted_flag]
    total, mapped, exceptions = st.columns(3)
    total.metric('Total Teams', len(active))
    mapped.metric('Teams with mapped employees', sum(overview.capacities[team.team_id].has_employees for team in active))
    exceptions.metric('Teams with future capacity exceptions',
        sum(overview.capacities[team.team_id].has_future_exceptions for team in active),
        help='A mapped employee has an exception ending today or later, including an ongoing exception.')
    st.divider()
    selected = st.session_state.get('selected_team_id', 0)
    if selected not in teams:
        selected = next(iter(teams), 0)
    labels = {item.id: item.label(get_current_locale()) for item in service.get_all_hierarchy_types()}
    event = team_tree(overview, selected, labels)
    if event:
        identity, action = event['id'], event['action']
        if action != 'create_root':
            selected = identity
            st.session_state['selected_team_id'] = selected
        frame = functions_frame(overview.functions)
        if action in {'create', 'create_root'}:
            _open_add_team_dialog(service, frame, parent_team_id=identity if action == 'create' else None)
        elif action == 'edit':
            _open_edit_team_dialog(service, identity, frame)
        elif action == 'delete':
            _open_delete_team_dialog(service, identity, teams[identity].team_name)
        elif action == 'undelete' and service.undelete_team(identity):
            st.toast('Team restored.')
            st.rerun()
    if selected in teams:
        _details(overview, selected)
