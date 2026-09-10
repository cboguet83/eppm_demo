"""The real public sign-in gate navigates its existing browser tab."""

import pytest

from tests.test_dialog_browser import popup_server as popup_server, expect, sync_playwright


_APP = '''
from pathlib import Path
from app.infrastructure.database.schema_init import init_db
from app.presentation.components.authentication import account_gate
from app.presentation.i18n import set_current_locale
from app.security import create_access_service
from app.shared.config.authentication import AuthenticationConfig
import secrets

database = str(Path(__file__).with_suffix('.db'))
init_db(database)
settings = AuthenticationConfig('development', 'http://localhost:8080/realms/eppm',
    'test', secrets.token_urlsafe(32), 'http://localhost:8501',
    secrets.token_urlsafe(48), local_http=True)
set_current_locale('en')
account_gate(create_access_service(database, settings), '')
'''


@pytest.mark.parametrize('popup_server', [_APP], indirect=True, ids=['sign-in'])
def test_sign_in_reuses_the_current_tab_for_the_login_endpoint(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route('**/auth/login', lambda route: route.fulfill(
                content_type='text/html', body='<h1>Provider sign-in</h1>'))
            page.goto(popup_server)
            sign_in = page.get_by_role('link', name='Sign in', exact=True)
            expect(sign_in).to_be_visible(timeout=30000)
            assert sign_in.get_attribute('target') in (None, '_self')
            expect(sign_in).to_have_css('background-color', 'rgb(196, 16, 57)')
            sign_in.click()
            expect(page).to_have_url(popup_server + '/auth/login')
            expect(page.get_by_role('heading', name='Provider sign-in')).to_be_visible()
            assert len(page.context.pages) == 1
        finally:
            browser.close()
