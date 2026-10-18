"""Native administrator project drafts and explicit authorized grant submission."""

from collections.abc import Iterator
from pathlib import Path
import re

import psycopg
import pytest

from tests.postgresql.browser import NativeBrowserServer, native_server
from tests.postgresql.conftest import AuthorizedFixture
from tests.test_dialog_browser import expect, sync_playwright
from tests.test_oidc_browser_e2e import select_option


_SCREEN = '''
import streamlit as st
from app.runtime import process_runtime
from app.presentation.pages.access_management import render_access_management
from app.presentation.i18n import set_current_locale
from tests.postgresql.browser import browser_access
st.set_page_config(layout='wide')
set_current_locale('en')
service = browser_access(process_runtime())
actor = service.actor(st.context.cookies.get('eppm_session', ''))
render_access_management(service, actor)
'''


@pytest.fixture
def access_server(authorized: AuthorizedFixture, tmp_path: Path) -> Iterator[NativeBrowserServer]:
    """Render production account controls with a real isolated administrator."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='Visible browser project' WHERE id=1")
    with native_server(authorized, tmp_path, _SCREEN, user_id=5) as server:
        yield server


def test_project_draft_survives_filtering_until_an_explicit_grant(
    access_server: NativeBrowserServer, authorized: AuthorizedFixture,
) -> None:
    """Repeat the failing interaction and verify its eventual persisted scope."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = access_server.new_page(browser)
            for _ in range(30):
                page.goto(access_server.origin)
                expect(page.get_by_role('heading', name='Application access', exact=True)).to_be_visible()
                select_option(page, 'Application account', re.compile(r'^3 ·'))
                select_option(page, 'Projects', re.compile('Visible browser project'))
                expect(page.get_by_role('checkbox', name=re.compile('Visible browser project'))).to_be_checked()
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute(
                    'SELECT count(*) FROM eppm.app_role_assignment WHERE user_id=3',
                ).fetchone()[0] == 0
            page.get_by_role('button', name='Grant access', exact=True).click()
            expect(page.get_by_role('button', name='Revoke assignment', exact=True)).to_be_visible()
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute(
                    'SELECT role,scope_json FROM eppm.app_role_assignment WHERE user_id=3',
                ).fetchall() == [('project_viewer', {'kind': 'projects', 'project_ids': [1], 'conditions': []})]
        finally:
            browser.close()
