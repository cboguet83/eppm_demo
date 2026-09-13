"""Allocation values stay local until submission in project and task dialogs."""

import psycopg
import pytest
from streamlit.proto.BackMsg_pb2 import BackMsg

from tests.test_dialog_browser import expect, sync_playwright
from tests.postgresql.browser import native_server


_APP = '''
import streamlit as st
from app.application.services.business_access import BusinessAccess
from app.main import create_planning_workspace
from app.presentation.pages.planning import _manage_project_resource_pools_dialog, _manage_task_resource_pools_dialog
from app.runtime import process_runtime
from tests.postgresql.browser import browser_access

resources = process_runtime()
authentication = browser_access(resources)
actor = authentication.actor(st.context.cookies.get('eppm_session', ''))
workspace = create_planning_workspace(resources, access=BusinessAccess(actor, authentication.policy))
OPEN_DIALOG
'''


@pytest.fixture
def popup_server(authorized, tmp_path, request):
    """Seed native allocation choices before starting the restricted screen."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='Project' WHERE id=1")
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date) VALUES(1,1,'Task','2026-01-01','2026-12-31')")
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) SELECT i,'Pool ' || i,3 FROM generate_series(1,103) i")
    with native_server(authorized, tmp_path, request.param) as server:
        yield server


@pytest.mark.parametrize('popup_server', [
    _APP.replace('OPEN_DIALOG', "_manage_project_resource_pools_dialog(1,'Project',workspace)"),
    _APP.replace('OPEN_DIALOG', "_manage_task_resource_pools_dialog(1,'Task',1,workspace)"),
], indirect=True, ids=['project', 'task'])
def test_pool_and_fte_changes_do_not_send_a_rerun_until_submitted(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = popup_server.new_page(browser, viewport={'width':1300,'height':1000})
            reruns = []
            def record(payload):
                if isinstance(payload, bytes):
                    message = BackMsg.FromString(payload)
                    if message.WhichOneof('type') == 'rerun_script':
                        reruns.append(message)
            page.on('websocket', lambda socket: socket.on('framesent', record))
            page.goto(popup_server.origin)
            dialog = page.get_by_role('dialog')
            pool = dialog.get_by_role('combobox')
            expect(pool).to_be_visible(timeout=30000)
            page.wait_for_function("document.querySelector('[data-testid=stApp]').dataset.testScriptState === 'notRunning'")
            reruns.clear()
            selection = dialog.get_by_test_id('stSelectbox')
            before = pool.input_value()
            pool.click()
            options = page.locator('[role=option]')
            expect(options.first).to_be_visible()
            options.nth(1).click()
            assert pool.input_value() != before
            fte = dialog.get_by_role('spinbutton')
            fte.fill('2.5')
            fte.press('Tab')
            page.wait_for_timeout(350)
            assert reruns == []
            expect(dialog).to_be_visible()
            assert float(fte.input_value()) == 2.5
            dialog.get_by_role('button', name='Assign Pool to', exact=False).click()
            expect(dialog.get_by_text('2.50 FTE', exact=True)).to_be_visible(timeout=30000)
        finally:
            browser.close()
