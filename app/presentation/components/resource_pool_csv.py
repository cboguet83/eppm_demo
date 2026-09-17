"""Resource-pool CSV download and atomic import controls."""

import streamlit as st

from app.application.services.resource_pool_csv import parse_pools
from app.application.services.resource_pools import ResourcePoolService
from app.presentation.components.csv_upload import project_csv_upload
from app.presentation.components.dialog import dialog
from app.presentation.components.resource_pool_dialogs import pool_errors


@dialog('Import resource pools')
@pool_errors
def _import_dialog(service: ResourcePoolService) -> None:
    """Preview catalog rows and apply them only on explicit submission."""
    st.caption('Known pool IDs are updated. Missing or unknown IDs create pools with automatically generated IDs. '
               'Parent IDs may refer to another row in this file. The whole import succeeds or is rolled back.')
    st.caption('Pools whose restoration would overallocate resources stay deleted. Other valid updates are imported, '
               'with detailed warnings for blocked restorations.')
    delete_missing = st.checkbox('Delete pools missing from the uploaded CSV', value=False,
        help='Unchecked: keep existing pools that are absent from the file. Checked: mark absent active pools as deleted, retaining their history and mappings. Include all pools you want to keep and their parent containers.',
        key='pool_csv_delete_missing')
    if delete_missing:
        st.warning('Active pools omitted from this CSV will be marked deleted. Include their parent containers when keeping child pools.')
    st.caption('Columns: name is required; blank capacity means unspecified; blank parent or hierarchy type means none. '
               'Pool type defaults to 1 and deleted_flag to false. Mappings, tags and capacity exceptions are unchanged.')
    st.link_button('Download CSV template', '/downloads/resource-pools/template.csv')
    upload = project_csv_upload('Resource pools CSV', key='pool_csv_upload')
    if upload is None:
        return
    rows = parse_pools(upload.encode('utf-8'))
    st.caption(f'{len(rows)} pool records ready to import.')
    st.dataframe([{'Pool ID': row.id, 'Name': row.name, 'Parent ID': row.parent_pool_id,
                   'Capacity (FTE)': row.capacity_fte, 'Deleted': row.deleted_flag} for row in rows],
                 hide_index=True)
    if st.button('Import pools', type='primary', key='pool_csv_submit'):
        result = service.import_csv(upload.encode('utf-8'), delete_missing=delete_missing)
        st.session_state['pool_csv_success'] = (f'Import successful: {result.created} pools created, '
                                               f'{result.updated} updated, {result.deactivated} marked deleted.')
        st.session_state['pool_csv_warnings'] = [
            f'{item.pool_name} (#{item.pool_id}) remains deleted: ' + ' '.join(item.reasons)
            for item in result.blocked_restorations] + list(result.allocation_warnings)
        st.rerun()


def pool_csv_controls(service: ResourcePoolService, *, show_deleted: bool = False) -> None:
    """Export the visible catalog and open a focused CSV import dialog."""
    message = st.session_state.pop('pool_csv_success', None)
    if message:
        st.success(message)
    for warning in st.session_state.pop('pool_csv_warnings', []):
        st.warning(warning)
    with st.container(horizontal=True):
        st.link_button('Export CSV',
                       f'/downloads/resource-pools/pools.csv?include_deleted={str(show_deleted).lower()}',
                       icon=':material/download:', type='primary')
        if st.button('Import CSV', key='pool_csv_import', icon=':material/upload:'):
            _import_dialog(service)
