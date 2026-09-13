"""Isolated native Finance component server with real session-authenticated CSV."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
import os
from pathlib import Path
from secrets import token_urlsafe
import socket
import subprocess
import sys
import time
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import urlopen

import psycopg
import pytest

from app.application.services.access import (
    AccessService, AuthorizationPolicy, SessionLimits, session_digest,
)
from app.infrastructure.postgresql.access import PostgresAccessGateway
from app.main import create_finance_service
from app.runtime import RuntimeResources

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page, ViewportSize
    from tests.postgresql.conftest import AuthorizedFixture


ROOT = Path(__file__).resolve().parents[2]


def browser_access(resources: RuntimeResources) -> AccessService:
    """Use native cookie resolution with the isolated fixture's deliberate clock."""
    policy = AuthorizationPolicy(lambda: 1000, SessionLimits())
    return AccessService(PostgresAccessGateway(resources.database, resources.key, policy), policy,
                         'https://issuer.example.test', lambda: token_urlsafe(32))


_SCREEN = '''
from datetime import date
import os
import streamlit as st
from app.application.services.business_access import BusinessAccess
from app.main import create_finance_service
from app.presentation.pages.finance import render_finance
from app.presentation.i18n import set_current_locale
from app.runtime import process_runtime
from tests.postgresql.finance_browser import browser_access

st.set_page_config(layout='wide')
resources = process_runtime()
access = browser_access(resources)
actor = access.actor(st.context.cookies.get('eppm_session', ''))
service = create_finance_service(resources, access=BusinessAccess(actor, access.policy))
service.today = lambda: date(2026, 6, 1)
scenario = os.environ['EPPM_TEST_FINANCE_SCENARIO']
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
from tests.postgresql.finance_browser import browser_access

resources = process_runtime()
access = browser_access(resources)

def export(actor: Actor, snapshot_id: int) -> str:
    service = create_finance_service(resources, access=BusinessAccess(actor, access.policy))
    service.today = lambda: date(2026, 6, 1)
    return service.export(snapshot_id)

app = st.App(Path(__file__).with_name('screen.py'),
             routes=FinanceDownloadRoutes(access, export).routes(), lifespan=resources.lifespan)
'''


@dataclass(frozen=True)
class FinanceBrowserServer:
    """A loopback URL and private cookie belonging only to this test database."""

    origin: str
    cookie: str = field(repr=False)

    def new_page(self, browser: Browser, *, viewport: ViewportSize | None = None) -> Page:
        """Open a real browser context with the fixture's opaque native session."""
        context = browser.new_context(viewport=viewport)
        context.add_cookies([{'name': 'eppm_session', 'value': self.cookie, 'url': self.origin}])
        return context.new_page()


@pytest.fixture
def popup_server(
    authorized: AuthorizedFixture, tmp_path: Path, request: pytest.FixtureRequest,
) -> Iterator[FinanceBrowserServer]:
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
    cookie = token_urlsafe(32)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.app_session SET session_hash=%s WHERE user_id=%s',
                           (session_digest(cookie), 3 if scenario == 'reader' else 4))
    (tmp_path / 'screen.py').write_text(_SCREEN, encoding='utf-8')
    launcher = tmp_path / 'asgi_finance.py'
    launcher.write_text(_ASGI, encoding='utf-8')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    environment = {key: value for key, value in os.environ.items() if key not in {
        'DATABASE_OPERATOR_URL', 'POSTGRES_TEST_ADMIN_URL', 'POSTGRES_PASSWORD', 'EPPM_RUNTIME_PASSWORD',
    }}
    environment.update(DATABASE_URL=authorized.setup.runtime_url, DATABASE_CONTEXT_KEY=authorized.key.hex(),
                       DATABASE_POOL_MIN='1', DATABASE_POOL_MAX='4', PYTHONPATH=str(ROOT),
                       EPPM_TEST_FINANCE_SCENARIO=scenario)
    origin = f'http://127.0.0.1:{port}'
    with (tmp_path / 'server.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([
            sys.executable, '-m', 'streamlit', 'run', str(launcher), '--server.address=127.0.0.1',
            f'--server.port={port}', '--server.headless=true', '--browser.gatherUsageStats=false',
            '--server.fileWatcherType=none',
        ], cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 40
            while True:
                try:
                    with urlopen(origin + '/_stcore/health', timeout=1) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError):
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('The isolated native Finance server failed to start.') from None
                    time.sleep(0.1)
            yield FinanceBrowserServer(origin, cookie)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
