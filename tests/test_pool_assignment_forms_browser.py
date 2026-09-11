"""Allocation values stay local until submission in project and task dialogs."""

import pytest
from streamlit.proto.BackMsg_pb2 import BackMsg

from tests.test_dialog_browser import popup_server as popup_server, expect, sync_playwright


_APP = '''
from pathlib import Path
from contextlib import closing
from app.infrastructure.database.schema_init import init_db
from app.infrastructure.database.connection import get_db
from app.operator_services import create_planning_workspace
from app.presentation.pages.planning import _manage_project_resource_pools_dialog, _manage_task_resource_pools_dialog
database=str(Path(__file__).with_suffix('.db'))
if not Path(database).exists():
    init_db(database)
    with closing(get_db(database)) as conn,conn:
        conn.execute("INSERT INTO project(id,name) VALUES(1,'Project')")
        conn.execute("INSERT INTO project_task(id,project_id,task_name,start_date,end_date) VALUES(1,1,'Task','2026-01-01','2026-12-31')")
        conn.executemany('INSERT INTO resource_pool(id,name,capacity_fte) VALUES(?,?,3)',[(i,f'Pool {i}') for i in range(1,104)])
workspace=create_planning_workspace(database)
OPEN_DIALOG
'''


@pytest.mark.parametrize('popup_server', [
    _APP.replace('OPEN_DIALOG', "_manage_project_resource_pools_dialog(1,'Project',workspace)"),
    _APP.replace('OPEN_DIALOG', "_manage_task_resource_pools_dialog(1,'Task',1,workspace)"),
], indirect=True, ids=['project', 'task'])
def test_pool_and_fte_changes_do_not_send_a_rerun_until_submitted(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width':1300,'height':1000})
            reruns = []
            def record(payload):
                if isinstance(payload, bytes):
                    message = BackMsg.FromString(payload)
                    if message.WhichOneof('type') == 'rerun_script':
                        reruns.append(message)
            page.on('websocket', lambda socket: socket.on('framesent', record))
            page.goto(popup_server)
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
