"""Browser checks for filter alignment and plain Settings labels."""

import pytest

from tests.test_dialog_browser import popup_server, sync_playwright, expect


_APP = '''
from types import SimpleNamespace
import streamlit as st
from app.presentation.pages.dashboard import _filters
from app.presentation.pages.settings import render_settings_view
from app.presentation.i18n import set_current_locale
set_current_locale('en')
class Catalog:
    def choices(self, catalog, active, key, match_all):
        return ['In Progress'] if key == 'status' else []
    def get_all_functions(self): return []
    def get_all_function_types(self): return []
    def get_all_teams(self): return []
    def get_all_employees(self): return []
    def get_all_hierarchy_types(self): return []
service = Catalog()
st.set_page_config(layout='wide')
_filters(service, SimpleNamespace(parameters=[], labels={}))
render_settings_view(SimpleNamespace(organization=service))
'''


@pytest.mark.parametrize('popup_server', [_APP], indirect=True)
def test_filter_buttons_align_and_settings_tabs_have_plain_labels(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 1500, 'height': 1100})
            page.goto(popup_server)
            clear = page.get_by_role('button', name='Clear all filters')
            advanced = page.get_by_role('button', name='Advanced filters')
            expect(clear).to_be_visible()
            expect(advanced).to_be_visible()
            assert abs(clear.bounding_box()['y'] - advanced.bounding_box()['y']) <= 2
            expect(page.get_by_role('heading', name='Settings', exact=True)).to_have_count(0)
            for label, catalog in [('Functions', 'functions'), ('Function Types', 'function_types'),
                                    ('Teams', 'teams'), ('Employees', 'employees')]:
                page.get_by_role('tab', name=label, exact=True).click()
                link = page.get_by_role('link', name='Export CSV', exact=True)
                expect(link).to_have_attribute('href', f'/downloads/organization/{catalog}.csv')
                frame = page.frame_locator('iframe').last
                expect(frame.locator('.search-icon,.ctx-icon')).to_have_count(0)
        finally:
            browser.close()
