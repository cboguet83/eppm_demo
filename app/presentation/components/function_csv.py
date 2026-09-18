"""Authenticated function CSV controls with an explicit optional deletion policy."""

from dataclasses import asdict

import streamlit as st

from app.application.services.organization import OrganizationService
from app.application.services.function_csv import parse_functions
from app.presentation.components.csv_upload import project_csv_upload
from app.presentation.components.dialog import dialog
from app.presentation.components.organization_dialogs import organization_errors


@dialog('Import functions')
@organization_errors
def import_functions_dialog(service: OrganizationService) -> None:
    """Preview function records and commit one validated import transaction."""
    st.caption('Known function IDs are updated. Unknown or missing IDs create functions with generated IDs. '
               'Parent IDs may reference another CSV row. Employee and team mappings are retained.')
    delete_missing = st.checkbox('Delete functions missing from the uploaded CSV', value=False,
        help='Unchecked: keep existing functions absent from this file. Checked: mark absent active functions as deleted, retaining their history and mappings. Include all functions you want to keep and their parents.',
        key='function_csv_delete_missing')
    if delete_missing:
        st.warning('Omitted active functions will be marked deleted. Include parents of all functions you keep active.')
    st.link_button('Download CSV template', '/downloads/functions/template.csv')
    upload = project_csv_upload('Functions CSV', key='function_csv_upload')
    if upload is None:
        return
    rows = parse_functions(upload.encode('utf-8'))
    st.dataframe([asdict(function) for function in rows], hide_index=True)
    if st.button('Import functions', type='primary', key='function_csv_submit'):
        result = service.import_functions_csv(upload.encode('utf-8'), delete_missing=delete_missing)
        st.session_state['function_csv_success'] = (f'Import successful: {result.created} functions created, '
            f'{result.updated} updated, {result.deleted} marked deleted.')
        st.rerun()


def function_csv_controls(service: OrganizationService, *, show_deleted: bool) -> None:
    """Export the displayed catalog or open the function import dialog."""
    message = st.session_state.pop('function_csv_success', None)
    if message:
        st.success(message)
    with st.container(horizontal=True):
        st.link_button('Export CSV', f'/downloads/functions/functions.csv?include_deleted={str(show_deleted).lower()}',
                       icon=':material/download:', type='primary')
        if st.button('Import CSV', key='function_csv_import', icon=':material/upload:'):
            import_functions_dialog(service)
