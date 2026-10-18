"""Authenticated native browser workflow for dictionary translations."""

import pytest

from tests.postgresql.browser import native_server

_playwright = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = _playwright.expect, _playwright.sync_playwright

_APP = '''
import streamlit as st
from app.runtime import process_runtime
from tests.postgresql.browser import browser_access
from app.application.services.business_access import BusinessAccess
from app.main import create_settings_workspace
from app.presentation.pages.settings import render_settings_view
from app.presentation.i18n import set_current_locale
runtime = process_runtime()
authentication = browser_access(runtime)
actor = authentication.actor(st.context.cookies.get('eppm_session',''))
set_current_locale('en')
st.session_state['rb_settings_section'] = 'project_configuration'
render_settings_view(create_settings_workspace(runtime,access=BusinessAccess(actor,authentication.policy)))
'''


def test_authenticated_settings_edits_explicit_translations_and_preserves_selection(authorized, tmp_path):
    with native_server(authorized,tmp_path,_APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser)
            page.goto(server.origin)
            name = page.get_by_role('textbox',name='Name',exact=True)
            expect(name).to_be_visible(timeout=30000)
            name.fill('Browser sponsor')
            page.get_by_role('textbox',name='French',exact=True).fill('Parrain navigateur')
            page.get_by_role('button',name='Save',exact=True).click()
            expect(page.get_by_role('combobox',name='Catalog entry',exact=True)).to_have_value('Browser sponsor')
            french = page.get_by_role('textbox',name='French',exact=True)
            expect(french).to_have_value('Parrain navigateur')
            expect(page.get_by_role('textbox',name='German',exact=True)).to_have_value('')
            french.fill('')
            page.get_by_role('button',name='Save',exact=True).click()
            expect(french).to_have_value('')
            page.get_by_role('tab',name='Event types',exact=True).click()
            page.get_by_role('tab',name='Project roles',exact=True).click()
            expect(page.get_by_role('textbox',name='Name',exact=True)).to_have_value('Browser sponsor')
            expect(page.get_by_test_id('stException')).to_have_count(0)
        finally:
            browser.close()
