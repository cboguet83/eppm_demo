"""Browser verification of paired tasks, editable alternatives and immutable saves."""

import re
from copy import deepcopy

import psycopg
import pytest

from tests.postgresql.browser import native_server
from tests.postgresql.test_project_plans import service, draft_task

api = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = api.expect, api.sync_playwright

SCREEN = '''
import streamlit as st
from app.application.services.business_access import BusinessAccess
from app.main import create_planning_workspace
from app.presentation.pages.project_plans import render_project_plans
from app.runtime import process_runtime
from tests.postgresql.browser import browser_access
st.set_page_config(layout='wide')
runtime=process_runtime()
authentication=browser_access(runtime)
actor=authentication.actor(st.context.cookies.get('eppm_session',''))
access=BusinessAccess(actor,authentication.policy)
render_project_plans(create_planning_workspace(runtime,access=access), 1)
'''


def test_paired_gantt_retains_missing_tasks_and_saves_drag_as_new_version(authorized, tmp_path):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date,project_plan_id) VALUES (1,'Design','2027-01-01','2027-01-05',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(1,'Removed task','2027-01-06','2027-01-08',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))")
    plans = service(authorized, 4)
    initial = plans.initialize(1)
    draft = deepcopy(initial.content)
    draft.tasks[0]['task_name'] = 'Renamed design'
    draft.tasks = draft.tasks[:1] + [draft_task(-1, 'Added task', '2027-01-09', '2027-01-10')]
    alternative = plans.save(1, initial.id, initial.revision, 'Option A', draft)
    with native_server(authorized, tmp_path, SCREEN) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1700, 'height': 1200})
            page.goto(server.origin)
            selector = page.get_by_role('combobox', name='Alternative plan', exact=True)
            selector.click(timeout=30000)
            page.get_by_role('option', name=re.compile('Option A')).click()
            table = page.get_by_role('table', name='Project plan comparison')
            expect(table.get_by_text('Removed task', exact=True)).to_be_visible()
            expect(table.get_by_text('Added task', exact=True)).to_be_visible()
            expect(table.locator('tr[data-task-id] .plan-reference')).to_have_count(2)
            expect(table.locator('tr[data-task-id] .plan-alternative')).to_have_count(2)
            page.screenshot(path=str(tmp_path / 'plan-comparison.png'), full_page=True)
            page.get_by_role('button', name='Edit alternative', exact=True).click()
            bar = page.get_by_role('button', name=re.compile('alternative: Renamed design'))
            bar.press('ArrowRight')
            expect(page.get_by_role('button', name='alternative: Renamed design · 2027-01-02 → 2027-01-06', exact=True)).to_be_visible()
            expect(table.locator('.plan-reference.editable')).to_have_count(0)
            page.get_by_role('textbox', name='New plan name', exact=True).fill('Shifted option')
            page.get_by_role('button', name='Save as new plan', exact=True).click()
            expect(page.get_by_role('button', name='Edit alternative', exact=True)).to_be_enabled()
            with psycopg.connect(authorized.setup.operator_url) as connection:
                from app.infrastructure.postgresql.plan_rows import read_plans
                metadata = connection.execute('SELECT id,name,is_current FROM eppm.project_plan WHERE project_id=1 ORDER BY version').fetchall()
                contents = read_plans(connection, [row[0] for row in metadata])
                rows = [(name, current, contents[identity]) for identity, name, current in metadata]
            assert [row[0] for row in rows] == ['Initial plan', 'Option A', 'Shifted option']
            assert rows[0][1] and not rows[1][1] and not rows[2][1]
            assert rows[0][2].tasks[0]['start_date'] == rows[1][2].tasks[0]['start_date'] == '2027-01-01'
            assert rows[2][2].tasks[0]['start_date'] == '2027-01-02'
        finally:
            browser.close()
