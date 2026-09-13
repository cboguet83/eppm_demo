"""Native full-shell browser fixture for portfolio layout and details readiness."""

import psycopg
import pytest

from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog, install_schema_catalog
from tests.postgresql.browser import native_server


_APP = '''
import streamlit as st
from app.application.services.business_access import BusinessAccess
from app.main import create_application_workspace
from app.presentation.i18n import set_current_locale
from app.presentation.shell import render_application
from app.runtime import process_runtime
from tests.postgresql.browser import browser_access

resources = process_runtime()
authentication = browser_access(resources)
actor = authentication.actor(st.context.cookies.get('eppm_session', ''))
access = BusinessAccess(actor, authentication.policy)
workspace = create_application_workspace(resources, access=access, authentication=authentication)
set_current_locale('en')
render_application(workspace)
'''


@pytest.fixture
def popup_server(authorized, tmp_path, request):
    """Keep operator setup outside the server and authenticate a business actor."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        ensure_reference_catalog(connection)
        install_schema_catalog(connection)
        connection.execute('DELETE FROM eppm.project WHERE id=3')
        connection.execute("UPDATE eppm.project SET name='Project ' || lpad(id::text,4,'0'),project_type_id=(SELECT id FROM eppm.project_type WHERE is_general)")
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date) VALUES(1,1,'First task','2026-01-01','2026-01-02'),(2,2,'Second task','2026-01-01','2026-01-02')")
    with native_server(authorized, tmp_path, request.param) as server:
        yield server
