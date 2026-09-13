"""Finance scenarios on the shared native session-authenticated server."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
import pytest

from app.main import create_finance_service
from app.runtime import RuntimeResources
from tests.postgresql.browser import NativeBrowserServer, native_server

if TYPE_CHECKING:
    from tests.postgresql.conftest import AuthorizedFixture


_SCREEN = '''
from datetime import date
import os
import streamlit as st
from app.application.services.business_access import BusinessAccess
from app.main import create_finance_service
from app.presentation.pages.finance import render_finance
from app.presentation.i18n import set_current_locale
from app.runtime import process_runtime
from tests.postgresql.browser import browser_access

st.set_page_config(layout='wide')
resources = process_runtime()
access = browser_access(resources)
actor = access.actor(st.context.cookies.get('eppm_session', ''))
service = create_finance_service(resources, access=BusinessAccess(actor, access.policy))
service.today = lambda: date(2026, 6, 1)
scenario = os.environ['EPPM_TEST_COMPONENT_SCENARIO']
set_current_locale('fr' if scenario == 'reader' else 'en')
st.session_state['shell_runs'] = st.session_state.get('shell_runs', 0) + 1
st.caption('Shell runs: ' + str(st.session_state['shell_runs']))
if scenario == 'navigation':
    page = st.sidebar.radio('Page', ['Finance', 'Dashboard'], key='test_page')
    if page == 'Finance':
        render_finance(service)
    else:
        st.header('Dashboard destination')
else:
    render_finance(service)
'''


_ASGI = '''
from datetime import date
from pathlib import Path
import streamlit as st
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor
from app.infrastructure.authentication.finance import FinanceDownloadRoutes
from app.main import create_finance_service
from app.runtime import process_runtime
from tests.postgresql.browser import browser_access

resources = process_runtime()
access = browser_access(resources)

def export(actor: Actor, snapshot_id: int) -> str:
    service = create_finance_service(resources, access=BusinessAccess(actor, access.policy))
    service.today = lambda: date(2026, 6, 1)
    return service.export(snapshot_id)

app = st.App(Path(__file__).with_name('screen.py'),
             routes=FinanceDownloadRoutes(access, export).routes(), lifespan=resources.lifespan)
'''


@pytest.fixture
def popup_server(
    authorized: AuthorizedFixture, tmp_path: Path, request: pytest.FixtureRequest,
) -> Iterator[NativeBrowserServer]:
    """Seed separately, then run a restricted native process with no operator URL."""
    scenario = request.param
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.wbs(code,description) VALUES('A.1','Known description')")
    resources = RuntimeResources(authorized.database, authorized.key)
    service = create_finance_service(resources, access=authorized.binding(4).access)
    service.today = lambda: date(2026, 6, 1)
    if scenario == 'exit-edit':
        for amount in ('42', '99'):
            service.save([{'code': 'A.1', 'amounts': {'2026': amount}}], base_id=None,
                         status='Draft', name='Plan ' + amount, year=2026)
    elif scenario == 'reader':
        service.save([{'code': 'A.1', 'amounts': {'2026': '42'}}], base_id=None,
                     status='Draft', name='Shared', year=2026)
    elif scenario == 'large':
        service.today = lambda: date(2021, 6, 1)
        service.save([{'code': f'WBS_{index}', 'amounts': {'2021': '1.00', '2026': '2.00'}} for index in range(1000)],
                     base_id=None, status='Draft', name='Large plan', year=2021)
    with native_server(authorized, tmp_path, _SCREEN, user_id=3 if scenario == 'reader' else 4,
                       scenario=scenario, launcher=_ASGI) as server:
        yield server
