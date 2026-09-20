"""Authenticated team CSV controls with an explicit optional deletion policy."""

import streamlit as st

from app.application.services.organization import OrganizationService
from app.application.services.team_csv import TEAM_CSV_COLUMNS, parse_teams
from app.presentation.components.csv_upload import project_csv_upload, reset_csv_upload
from app.presentation.components.dialog import dialog
from app.presentation.components.organization_dialogs import organization_errors


@dialog('Import teams')
@organization_errors
def import_teams_dialog(service: OrganizationService) -> None:
    """Preview team records and commit one validated import transaction."""
    st.caption('Known team IDs are updated. Unknown or missing IDs create teams with generated IDs. '
               'Parent IDs may reference another CSV row. Function memberships are retained.')
    delete_missing = st.checkbox('Delete teams missing from the uploaded CSV', value=False,
        help='Unchecked: keep existing teams absent from this file. Checked: mark absent active teams as deleted, retaining their history and mappings. Include all teams you want to keep and their parents.',
        key='team_csv_delete_missing')
    if delete_missing:
        st.warning('Omitted active teams will be marked deleted. Include parents of all teams you keep active.')
    st.link_button('Download CSV template', '/downloads/teams/template.csv')
    upload = project_csv_upload('Teams CSV', key='team_csv_upload')
    if upload is None:
        return
    rows = parse_teams(upload.encode('utf-8'))
    st.dataframe([{column: getattr(team, column) for column in TEAM_CSV_COLUMNS} for team in rows], hide_index=True)
    if st.button('Import teams', type='primary', key='team_csv_submit'):
        result = service.import_teams_csv(upload.encode('utf-8'), delete_missing=delete_missing)
        st.session_state['team_csv_success'] = (f'Import successful: {result.created} teams created, '
            f'{result.updated} updated, {result.deleted} marked deleted.')
        st.rerun()


def team_csv_controls(service: OrganizationService, *, show_deleted: bool) -> None:
    """Export the displayed catalog or open the team import dialog."""
    message = st.session_state.pop('team_csv_success', None)
    if message:
        st.success(message)
    with st.container(horizontal=True):
        st.link_button('Export CSV', f'/downloads/teams/teams.csv?include_deleted={str(show_deleted).lower()}',
                       icon=':material/download:', type='primary')
        if st.button('Import CSV', key='team_csv_import', icon=':material/upload:'):
            reset_csv_upload('team_csv_upload')
            import_teams_dialog(service)
