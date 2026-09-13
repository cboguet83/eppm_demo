"""Dashboard browser scenarios seeded outside the restricted application process."""

from datetime import date

import psycopg
import pytest

from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.main import create_finance_service
from app.runtime import RuntimeResources
from tests.postgresql.browser import native_server


_SCREEN = '''
from datetime import date
import streamlit as st
from app.application.services.business_access import BusinessAccess
from app.main import create_dashboard_service
from app.presentation.pages.dashboard import render_dashboard
from app.presentation.i18n import set_current_locale
from app.runtime import process_runtime
from tests.postgresql.browser import browser_access

st.set_page_config(layout='wide')
resources = process_runtime()
authentication = browser_access(resources)
actor = authentication.actor(st.context.cookies.get('eppm_session', ''))
service = create_dashboard_service(resources, access=BusinessAccess(actor, authentication.policy))
service.today = lambda: date(2026, 6, 1)
set_current_locale('en')
st.session_state['shell_runs'] = st.session_state.get('shell_runs', 0) + 1
st.caption('Shell runs: ' + str(st.session_state['shell_runs']))
if st.session_state.get('nav_redirect'):
    st.write('Planning projects: ' + str(st.session_state['dashboard_planning_projects']))
else:
    render_dashboard(service)
'''


@pytest.fixture
def popup_server(authorized, tmp_path, request):
    """Seed 1,000 projects, exact Finance shares and an active issue separately."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        ensure_reference_catalog(connection)
        connection.execute("UPDATE eppm.project SET name='Project ' || lpad(id::text,4,'0')")
        connection.execute("INSERT INTO eppm.project(id,name) SELECT i,'Project ' || lpad(i::text,4,'0') FROM generate_series(4,1000) i")
        connection.execute("INSERT INTO eppm.wbs(id,code,description) VALUES(1,'A','Example')")
        connection.execute('INSERT INTO eppm.project_wbs(project_id,wbs_id,percentage) VALUES(1,1,50)')
        if request.param == 'shared-budget':
            connection.execute('INSERT INTO eppm.project_wbs(project_id,wbs_id,percentage) VALUES(2,1,25)')
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Pool A',1),(2,'Pool B',1)")
        connection.cursor().executemany(
            "INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date) VALUES(%s,%s,%s,'2026-01-01','2026-03-31')",
            [(1, 1, 1), (1, 2, 2), (2, 1, 1), (2, 2, 1)],
        )
        blocker = connection.execute("SELECT id FROM eppm.project_event_type WHERE system_code='blocking_point'").fetchone()[0]
        connection.execute("INSERT INTO eppm.project_log_event(project_id,title,description,comment,event_type_id,status) VALUES(1,'Delivery blocked',%s,'Read only',%s,'active')",
                           ('First line\nSecond line', blocker))
    finance = create_finance_service(RuntimeResources(authorized.database, authorized.key), access=authorized.binding(4).access)
    finance.today = lambda: date(2026, 6, 1)
    finance.save([{'code': 'A', 'amounts': {'2026': '100.01', '2027': '200'}}],
                 base_id=None, name='Approved plan', status='Approved', year=2026)
    with native_server(authorized, tmp_path, _SCREEN) as server:
        yield server
