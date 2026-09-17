"""Resource-pool CSV download and atomic import controls."""

import streamlit as st

from app.application.services.resource_pool_csv import export_pools, parse_pools
from app.application.services.resource_pools import ResourcePoolService
from app.domain.resources.models import ResourcePool
from app.presentation.components.dialog import dialog
from app.presentation.components.resource_pool_dialogs import pool_errors


@dialog('Import resource pools')
@pool_errors
def _import_dialog(service: ResourcePoolService) -> None:
    """Preview catalog rows and apply them only on explicit submission."""
    st.caption('Known pool IDs are updated. Missing or unknown IDs create pools with automatically generated IDs. '
               'Parent IDs may refer to another row in this file. The whole import succeeds or is rolled back.')
    st.caption('Columns: name is required; blank capacity means unspecified; blank parent or hierarchy type means none. '
               'Pool type defaults to 1 and deleted_flag to false. Mappings, tags and capacity exceptions are unchanged.')
    st.download_button('Download CSV template', export_pools([]).encode('utf-8-sig'),
                       'resource_pools_template.csv', 'text/csv', key='pool_csv_template')
    upload = st.file_uploader('Resource pools CSV', type=['csv'], key='pool_csv_upload')
    if upload is None:
        return
    rows = parse_pools(upload.getvalue())
    st.caption(f'{len(rows)} pool records ready to import.')
    st.dataframe([{'Pool ID': row.id, 'Name': row.name, 'Parent ID': row.parent_pool_id,
                   'Capacity (FTE)': row.capacity_fte, 'Deleted': row.deleted_flag} for row in rows],
                 hide_index=True)
    if st.button('Import pools', type='primary', key='pool_csv_submit'):
        result = service.import_csv(upload.getvalue())
        st.session_state['pool_csv_success'] = f'Import successful: {result.created} pools created, {result.updated} updated.'
        st.rerun()


def pool_csv_controls(service: ResourcePoolService, pools: list[ResourcePool]) -> None:
    """Export the visible catalog and open a focused CSV import dialog."""
    message = st.session_state.pop('pool_csv_success', None)
    if message:
        st.success(message)
    with st.container(horizontal=True):
        st.download_button('Export CSV', export_pools(pools).encode('utf-8-sig'),
                           'resource_pools.csv', 'text/csv', key='pool_csv_export',
                           icon=':material/download:')
        if st.button('Import CSV', key='pool_csv_import', icon=':material/upload:'):
            _import_dialog(service)
