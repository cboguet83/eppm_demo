"""Current portfolio editing is opt-in and comparison edits only alternatives."""

from copy import deepcopy
import re

import psycopg
import pytest

from tests.postgresql.browser import native_server
from tests.postgresql.test_project_dependency_browser import _APP
from tests.postgresql.test_project_plans import service, draft_task
from app.infrastructure.postgresql.plan_rows import read_plans

api = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = api.expect, api.sync_playwright


def drag(page, bar):
    box = bar.bounding_box()
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 76, y, steps=8)
    page.mouse.up()


def scenario_menu(frame):
    frame.locator('#frozen-row-proj-1').click(button='right')
    frame.get_by_text('Scenario management', exact=True).hover()


def test_opt_in_editing_and_alternative_lanes(authorized, tmp_path):
    plans = service(authorized, 4)
    initial = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='In Progress'")
        connection.execute("INSERT INTO eppm.project_task(project_id,project_plan_id,task_name,start_date,end_date) VALUES(1,%s,'Build','2027-01-01','2027-01-05'),(1,%s,'Active only','2027-01-07','2027-01-09')", (initial.id, initial.id))
    baseline = plans.baseline_current(1)
    initial = next(row for row in plans.list_plans(1) if row.is_current)
    content = deepcopy(initial.content)
    content.tasks = content.tasks[:1] + [draft_task(-1, 'Extra alternative step', '2027-01-10', '2027-01-12')]
    alternative = plans.save(1, initial.id, initial.revision, 'Option A', content)
    extra = alternative.content.tasks[1]['id']
    with native_server(authorized, tmp_path, _APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1700, 'height': 1200})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(server.origin)
            frame = page.frame_locator('iframe[title*="interactive_gantt"]')
            edit = frame.get_by_role('checkbox', name='Enable edit mode', exact=True)
            expect(edit).not_to_be_checked(timeout=40000)
            frame.locator('#btn-mode-day').click()
            active_bar = frame.locator('#timeline-row-1 .gantt-bar-wrapper')
            expect(active_bar).to_be_visible()
            drag(page, active_bar)
            scenario_menu(frame)
            expect(frame.locator('#ctx-project-baseline')).to_be_hidden()
            expect(frame.locator('#ctx-delete-baseline')).to_be_hidden()
            frame.get_by_text('Display an alternative scenario', exact=True).click()
            picker = page.get_by_role('combobox', name='Alternative scenario', exact=True)
            picker.click()
            expect(page.get_by_role('option', name=re.compile('baseline'))).to_have_count(0)
            page.get_by_role('option', name=re.compile('Option A')).click()
            page.get_by_role('button', name='Display scenario', exact=True).click()
            alt_bar = frame.locator('#timeline-row-1 .alternative-bar')
            expect(alt_bar).to_be_visible()
            expect(frame.locator(f'#frozen-row-alternative-1-{extra}')).to_contain_text('Extra alternative step')
            assert frame.locator(f'#frozen-row-alternative-1-{extra} .task-title').evaluate('(el)=>getComputedStyle(el).color') == 'rgb(147, 51, 234)'
            assert alt_bar.bounding_box()['y'] > active_bar.bounding_box()['y'] + active_bar.bounding_box()['height']
            expect(frame.locator('#timeline-row-2 .alternative-bar')).to_have_count(0)
            drag(page, alt_bar)
            edit.check()
            drag(page, active_bar)
            drag(page, alt_bar)
            expect(alt_bar).to_have_attribute('title', 'Option A: 2027-01-03 → 2027-01-07', timeout=15000)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                saved = read_plans(connection, [initial.id, baseline.id, alternative.id])
            assert saved[initial.id] == initial.content
            assert saved[baseline.id] == baseline.content
            assert saved[alternative.id].tasks[0]['start_date'] == '2027-01-03'
            page.screenshot(path=str(tmp_path / 'alternative-lanes.png'), full_page=True)
            frame.get_by_role('checkbox', name='Show baseline', exact=True).check()
            expect(frame.locator('.alternative-bar')).to_have_count(0)
            expect(frame.locator('.baseline-line')).not_to_have_count(0)
            scenario_menu(frame)
            page.once('dialog', lambda dialog: dialog.accept())
            frame.get_by_text('Delete baseline', exact=True).click()
            expect(frame.locator('.baseline-line')).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT id FROM eppm.project_plan WHERE is_baseline').fetchall() == []
            assert not errors
        finally:
            browser.close()
