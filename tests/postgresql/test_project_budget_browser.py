"""Browser verification of the unified WBS table and exact monetary edits."""

from pathlib import Path

import psycopg
import pytest

from tests.postgresql.browser import native_server

playwright_api = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = playwright_api.expect, playwright_api.sync_playwright

SCREEN = '''
import streamlit as st
from app.application.services.business_access import BusinessAccess
from app.main import create_project_budget_service
from app.presentation.components.project_budget import render_project_budget
from app.runtime import process_runtime
from tests.postgresql.browser import browser_access
st.set_page_config(layout='wide')
runtime = process_runtime()
authentication = browser_access(runtime)
actor = authentication.actor(st.context.cookies.get('eppm_session'))
render_project_budget(1, create_project_budget_service(runtime, access=BusinessAccess(actor, authentication.policy)))
'''


def test_business_admin_saves_live_actual_commitment_and_cancels_unsaved_edits(authorized, tmp_path):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.wbs(id,code) VALUES(1,'P.1'),(2,'P.2')")
        connection.execute('INSERT INTO eppm.project_wbs VALUES(1,1,100),(1,2,100)')
    with native_server(authorized, tmp_path, SCREEN) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1600, 'height': 950})
            page.goto(server.origin)
            live = page.get_by_role('textbox', name='P.1 Budget-Live 2026', exact=True)
            expect(live).to_be_visible(timeout=30000)
            assert page.get_by_role('textbox', name='P.1 Budget - Approved 2026', exact=True).count() == 0
            live.fill('123.45')
            page.get_by_role('textbox', name='P.1 Actual 2026', exact=True).fill('20.01')
            page.get_by_role('textbox', name='P.1 Commitment 2026', exact=True).fill('80.05')
            page.get_by_role('button', name='Save changes', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Budget saved.')).to_be_visible()
            expect(live).to_have_value('123.45')
            live.fill('999')
            page.get_by_role('button', name='Cancel', exact=True).click()
            expect(live).to_have_value('123.45')
            live.fill('-1')
            page.get_by_role('button', name='Save changes', exact=True).click()
            expect(page.get_by_role('alert').filter(has_text='nonnegative')).to_be_visible()
            live.fill('200')
            page.get_by_role('button', name='Save changes', exact=True).click()
            expect(live).to_have_value('200.00')
            screenshot = Path('.local/project-budget-browser.png').resolve()
            page.screenshot(path=str(screenshot), full_page=True)
            page.reload()
            expect(live).to_have_value('200.00', timeout=30000)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                records = connection.execute('SELECT financial_record_type,amount::text FROM eppm.project_financial_transaction WHERE project_id=1').fetchall()
            assert len(records) == 3
            assert dict(records) == {'LIVE_BUDGET': '200.00', 'ACTUAL': '20.01', 'COMMITMENT': '80.05'}
        finally:
            browser.close()
