"""Verify immediate blanking and completed-page reveal in a real browser."""

import pytest

from tests.test_dialog_browser import popup_server, sync_playwright, expect


_APP = '''
import time
import streamlit as st
from app.presentation.shell import render_application
from app.presentation.components.application_workspace import ApplicationWorkspace
from app.presentation.navigation import PAGE_PORTFOLIO, PAGE_PLANNING

def slow():
    st.write('First destination content')
    time.sleep(1)
    st.write('Destination ready')

render_application(ApplicationWorkspace('transition-test', {
    PAGE_PORTFOLIO: lambda: st.write('Original page'),
    PAGE_PLANNING: slow,
}, None))
'''


@pytest.mark.parametrize('popup_server', [_APP], indirect=True)
def test_navigation_blanks_old_page_until_destination_ready(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(popup_server)
            expect(page.get_by_text('Original page', exact=True)).to_be_visible()
            page.wait_for_selector('#eppm-page-transition', state='attached')
            page.get_by_text('Planning & Milestones', exact=True).click()
            expect(page.locator('#eppm-page-transition')).to_be_visible()
            expect(page.locator('[data-testid="stMain"]')).to_be_hidden()
            expect(page.get_by_text('Destination ready', exact=True)).to_be_visible()
            expect(page.locator('#eppm-page-transition')).to_be_hidden()
            expect(page.get_by_text('Original page', exact=True)).to_have_count(0)
        finally:
            browser.close()
