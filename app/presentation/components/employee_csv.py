"""Authenticated employee CSV controls with an explicit optional deletion policy."""

from dataclasses import asdict

import streamlit as st

from app.application.services.organization import OrganizationService
from app.application.exceptions import OrganizationStorageError
from app.application.services.employee_csv import parse_employees
from app.presentation.components.csv_upload import project_csv_upload, reset_csv_upload
from app.presentation.components.dialog import dialog
from app.presentation.components.organization_dialogs import organization_errors


@dialog('Import employees')
@organization_errors
def import_employees_dialog(service: OrganizationService) -> None:
    """Preview employee records and commit one validated import transaction."""
    st.caption('Known employee IDs are updated. Unknown or missing IDs create employees with generated IDs. '
               'Calendar exceptions and pool mappings are retained.')
    delete_missing = st.checkbox('Delete employees missing from the uploaded CSV', value=False,
        help='Unchecked: keep existing employees absent from this file. Checked: mark absent active employees as deleted, retaining their history and mappings. Include all employees you want to keep.',
        key='employee_csv_delete_missing')
    if delete_missing:
        st.warning('Omitted active employees will be marked deleted.')
    st.caption('function_id assigns one function at 100%. For multiple functions, use function_assignments as a JSON array, '
               'for example [{"function_id": 1, "allocation_pct": 60}, {"function_id": 2, "allocation_pct": 40}]. '
               'Omit both assignment columns to keep existing assignments; use [] to clear them.')
    st.link_button('Download CSV template', '/downloads/employees/template.csv')
    upload = project_csv_upload('Employees CSV', key='employee_csv_upload')
    if upload is None:
        return
    try:
        rows = parse_employees(upload.encode('utf-8'))
    except ValueError as error:
        st.error('Employee import failed while reading the CSV. No changes were saved.')
        st.text(str(error))
        return
    st.dataframe([asdict(employee) for employee in rows], hide_index=True)
    if st.button('Import employees', type='primary', key='employee_csv_submit'):
        try:
            result = service.import_employees_csv(upload.encode('utf-8'), delete_missing=delete_missing)
        except (ValueError, OrganizationStorageError) as error:
            st.error('Employee import failed during validation or database save. No changes were saved.')
            st.text(str(error))
            return
        st.session_state['employee_csv_success'] = (f'Import successful: {result.created} employees created, '
            f'{result.updated} updated, {result.deleted} marked deleted.')
        st.rerun()


def employee_csv_controls(service: OrganizationService, *, show_deleted: bool) -> None:
    """Export the displayed catalog or open the employee import dialog."""
    message = st.session_state.pop('employee_csv_success', None)
    if message:
        st.success(message)
    with st.container(horizontal=True):
        st.link_button('Export CSV', f'/downloads/employees/employees.csv?include_deleted={str(show_deleted).lower()}',
                       icon=':material/download:', type='primary')
        if st.button('Import CSV', key='employee_csv_import', icon=':material/upload:'):
            reset_csv_upload('employee_csv_upload')
            st.session_state['employee_csv_delete_missing'] = False
            import_employees_dialog(service)
