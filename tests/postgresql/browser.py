"""Loopback component servers using restricted native pools and opaque sessions."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
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

from app.application.services.access import (
    AccessService, AuthorizationPolicy, SessionLimits, session_digest,
)
from app.infrastructure.postgresql.access import PostgresAccessGateway
from app.runtime import RuntimeResources

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page, ViewportSize
    from tests.postgresql.conftest import AuthorizedFixture


ROOT = Path(__file__).resolve().parents[2]

_ASGI = '''
from pathlib import Path
import streamlit as st
from app.runtime import process_runtime

resources = process_runtime()
app = st.App(Path(__file__).with_name('screen.py'), lifespan=resources.lifespan)
'''


def browser_access(resources: RuntimeResources) -> AccessService:
    """Resolve native cookie sessions at the isolated fixture's deliberate clock."""
    policy = AuthorizationPolicy(lambda: 1000, SessionLimits())
    return AccessService(PostgresAccessGateway(resources.database, resources.key, policy), policy,
                         'https://issuer.example.test', lambda: token_urlsafe(32))


@dataclass(frozen=True)
class NativeBrowserServer:
    """A loopback URL and private cookie belonging only to this test database."""

    origin: str
    cookie: str = field(repr=False)

    def new_page(self, browser: Browser, *, viewport: ViewportSize | None = None) -> Page:
        """Open a browser context with the fixture's opaque native session."""
        context = browser.new_context(viewport=viewport)
        context.add_cookies([{'name': 'eppm_session', 'value': self.cookie, 'url': self.origin}])
        return context.new_page()


@contextmanager
def native_server(
    authorized: AuthorizedFixture, directory: Path, screen: str, *, user_id: int = 4,
    scenario: str = '', launcher: str = _ASGI,
) -> Iterator[NativeBrowserServer]:
    """Run a restricted process after parent setup; terminate only that process.

    Args:
        authorized: Isolated migrated database and its separately seeded accounts.
        directory: Test-owned script/log directory.
        screen: Trusted test source that renders the component under test.
        user_id: Seeded account whose session cookie belongs to this browser.
        scenario: Optional test scenario passed to the component server.
        launcher: Trusted ASGI source, optionally including production HTTP routes.

    Yields:
        The loopback server and an opaque native cookie. OIDC login is tested
        separately by the application browser suite.
    """
    cookie = token_urlsafe(32)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.app_session SET session_hash=%s WHERE user_id=%s',
                           (session_digest(cookie), user_id))
    (directory / 'screen.py').write_text(screen, encoding='utf-8')
    script = directory / 'asgi_component.py'
    script.write_text(launcher, encoding='utf-8')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    environment = {key: value for key, value in os.environ.items() if key not in {
        'DATABASE_OPERATOR_URL', 'POSTGRES_TEST_ADMIN_URL', 'POSTGRES_PASSWORD', 'EPPM_RUNTIME_PASSWORD',
    }}
    environment.update(DATABASE_URL=authorized.setup.runtime_url, DATABASE_CONTEXT_KEY=authorized.key.hex(),
                       DATABASE_POOL_MIN='1', DATABASE_POOL_MAX='4', PYTHONPATH=str(ROOT),
                       EPPM_TEST_COMPONENT_SCENARIO=scenario)
    origin = f'http://127.0.0.1:{port}'
    with (directory / 'server.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([
            sys.executable, '-m', 'streamlit', 'run', str(script), '--server.address=127.0.0.1',
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
                        raise RuntimeError('The isolated native component server failed to start.') from None
                    time.sleep(0.1)
            yield NativeBrowserServer(origin, cookie)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
