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


def display_alternative(page, frame, name='Option A'):
    scenario_menu(frame)
    frame.get_by_text('Display an alternative scenario', exact=True).click()
    page.get_by_role('combobox', name='Alternative scenario', exact=True).click()
    page.get_by_role('option', name=re.compile(name)).click()
    page.get_by_role('button', name='Display scenario', exact=True).click()
    expect(frame.locator('.alternative-bar').first).to_be_visible()


def test_create_named_draft_opens_light_blue_comparison_and_copies_allocations(authorized, tmp_path):
    plans = service(authorized, 4)
    initial = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='In Progress'")
        connection.execute("INSERT INTO eppm.project_task(project_id,project_plan_id,task_name,start_date,end_date,progress_pct) VALUES(1,%s,'Build','2027-01-01','2027-01-05',35)", (initial.id,))
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Pool',2)")
        connection.execute('''INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,project_plan_id,fte_assigned)
            VALUES(1,1,1,%s,0.5)''', (initial.id,))
    initial = next(row for row in plans.list_plans(1) if row.is_current)
    with native_server(authorized, tmp_path, _APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width':1700, 'height':1200})
            page.goto(server.origin)
            frame = page.frame_locator('iframe[title*="interactive_gantt"]')
            edit = frame.get_by_role('checkbox', name='Enable edit mode', exact=True)
            expect(edit).not_to_be_checked(timeout=40000)
            scenario_menu(frame)
            expect(frame.locator('#ctx-create-alternative')).to_be_hidden()
            frame.locator('#frozen-row-proj-1').click()
            edit.check()
            scenario_menu(frame)
            frame.get_by_text('Create alternative scenario', exact=True).click()
            name = page.get_by_role('textbox', name='Scenario name', exact=True)
            expect(name).to_be_visible()
            page.get_by_role('button', name='Create scenario', exact=True).click()
            expect(page.get_by_text('Plan name is required.', exact=True)).to_be_visible()
            name.fill('  Resource option  ')
            page.get_by_role('button', name='Create scenario', exact=True).click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            bar = frame.locator('#timeline-row-1 .alternative-bar')
            expect(bar).to_be_visible()
            assert bar.evaluate('(el)=>getComputedStyle(el).backgroundColor') == 'rgb(125, 211, 252)'
            assert frame.locator('#frozen-row-1').evaluate('(el)=>getComputedStyle(el).backgroundColor') == 'rgb(224, 242, 254)'
            expect(edit).to_be_checked()
            expect(page.get_by_role('button', name='Close alternative view', exact=True)).to_be_visible()
            with psycopg.connect(authorized.setup.operator_url) as connection:
                alternative_id, status, source, active = connection.execute('''SELECT p.id,s.code,p.source_plan_id,p.is_current
                    FROM eppm.project_plan p JOIN eppm.plan_status s ON s.id=p.status_id
                    WHERE p.project_id=1 AND p.name='Resource option' ''').fetchone()
                contents = read_plans(connection, [initial.id, alternative_id])
                count = connection.execute('SELECT count(*) FROM eppm.project_plan WHERE project_id=1').fetchone()[0]
            assert (status, source, active, count) == ('draft', initial.id, False, 2)
            assert contents[initial.id] == contents[alternative_id] == initial.content
            page.mouse.move(10, 700)
            page.screenshot(path=str(tmp_path / 'created-alternative.png'), full_page=True)
        finally:
            browser.close()


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
            expect(page.get_by_text('Enable edit mode to reschedule tasks.', exact=False)).to_have_count(0)
            expect(page.get_by_role('button', name='Close alternative view', exact=True)).to_have_count(0)
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
            expect(page.get_by_role('button', name='Close alternative view', exact=True)).to_be_visible()
            expect(frame.locator(f'#frozen-row-alternative-1-{extra}')).to_contain_text('Extra alternative step')
            assert frame.locator(f'#frozen-row-alternative-1-{extra} .task-title').evaluate('(el)=>getComputedStyle(el).color') == 'rgb(2, 132, 199)'
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
            expect(page.get_by_role('button', name='Close alternative view', exact=True)).to_have_count(0)
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


def test_alternative_context_edits_dependencies_hide_reload_and_confirm_activation(authorized, tmp_path):
    from app.application.services.collaboration import CollaborationService
    from tests.postgresql.test_collaboration import gateway

    CollaborationService(gateway(authorized)).save_catalog('event_type', 'General information')
    plans = service(authorized, 4)
    initial = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='In Progress'")
        connection.execute("INSERT INTO eppm.project_task(project_id,project_plan_id,task_name,start_date,end_date) VALUES(1,%s,'Build','2027-01-01','2027-01-05')", (initial.id,))
    initial = next(row for row in plans.list_plans(1) if row.is_current)
    content = deepcopy(initial.content)
    content.tasks.append(draft_task(-1, 'Extra step', '2027-01-10', '2027-01-12'))
    content.dependencies = [dict(task_id=-1, predecessor_task_id=1, predecessor_project_id=None, link_type='FS', lag_days=0)]
    alternative = plans.save(1, initial.id, initial.revision, 'Option A', content)
    plans.change(1, alternative.id, alternative.revision, 'status', 'approved')
    extra = alternative.content.tasks[1]['id']
    with native_server(authorized, tmp_path, _APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width':1700, 'height':1200})
            page.goto(server.origin)
            frame = page.frame_locator('iframe[title*="interactive_gantt"]')
            edit = frame.get_by_role('checkbox', name='Enable edit mode', exact=True)
            expect(edit).not_to_be_checked(timeout=40000)
            display_alternative(page, frame)
            frame.locator('#frozen-row-proj-1').click(button='right')
            expect(frame.locator('#ctx-project-log-event')).to_be_visible()
            frame.locator('#ctx-project-log-event').click()
            expect(page.get_by_role('dialog')).to_be_visible()
            page.get_by_role('dialog').get_by_role('button', name='Cancel', exact=True).click()
            frame.locator('#chk-internal-links').check()
            expect(frame.locator('.alternative-dependency')).to_have_count(1)
            edit.check()
            frame.locator('#timeline-row-1 .alternative-bar').click(button='right')
            for identity in ['ctx-label-edit-step', 'ctx-label-add-step', 'ctx-label-delete-step', 'ctx-label-task-tags', 'ctx-label-task-pools']:
                expect(frame.locator('#'+identity)).to_be_visible()
            frame.locator('#ctx-label-edit-step').click()
            page.get_by_role('textbox', name='Step name', exact=True).fill('Alternative build')
            page.get_by_role('button', name='Save alternative', exact=True).click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            frame.locator('#frozen-row-proj-1').click(button='right')
            frame.locator('#ctx-project-add-step').click()
            page.get_by_role('textbox', name='Step name', exact=True).fill('New scenario step')
            page.get_by_role('button', name='Save alternative', exact=True).click()
            expect(frame.locator('.alternative-only .task-title', has_text='New scenario step')).to_be_visible()
            frame.locator(f'#frozen-row-alternative-1-{extra}').click(button='right')
            page.once('dialog', lambda dialog: dialog.accept())
            frame.locator('#ctx-label-delete-step').click()
            expect(frame.locator(f'#frozen-row-alternative-1-{extra}')).to_have_count(0)
            expect(frame.locator('.alternative-dependency')).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                saved = read_plans(connection, [initial.id, alternative.id])
            assert saved[initial.id] == initial.content
            assert [row['task_name'] for row in saved[alternative.id].tasks] == ['Alternative build', 'New scenario step']
            frame.locator('#timeline-row-1 .alternative-bar').click(button='right')
            frame.locator('#ctx-label-complete-step').click()
            expect(frame.locator('#timeline-row-1 .alternative-bar > div').first).to_have_attribute('style', re.compile('width:100%'))
            with psycopg.connect(authorized.setup.operator_url) as connection:
                saved = read_plans(connection, [initial.id, alternative.id])
            assert saved[initial.id].tasks[0]['progress_pct'] == 0
            assert saved[alternative.id].tasks[0]['progress_pct'] == 100
            scenario_menu(frame)
            frame.locator('#ctx-hide-alternative').click()
            expect(frame.locator('.alternative-bar')).to_have_count(0)
            close = page.get_by_role('button', name='Close alternative view', exact=True)
            expect(close).to_have_count(0)
            display_alternative(page, frame)
            expect(close).to_be_visible()
            clear = page.get_by_role('button', name='Clear all filters', exact=True)
            clear_box, close_box = clear.bounding_box(), close.bounding_box()
            assert 0.45 < clear_box['width'] / close_box['width'] < 0.55
            assert clear_box['x'] + clear_box['width'] < close_box['x']
            page.screenshot(path=str(tmp_path / 'alternative-toolbar.png'), full_page=True)
            close.click()
            expect(frame.locator('.alternative-bar')).to_have_count(0)
            expect(close).to_have_count(0)
            expect(frame.locator('#frozen-row-proj-1')).to_be_visible()
            expect(edit).to_be_checked()
            display_alternative(page, frame)
            page.reload()
            expect(frame.locator('#frozen-row-proj-1')).to_be_visible(timeout=40000)
            expect(frame.locator('.alternative-bar')).to_have_count(0)
            expect(edit).not_to_be_checked()
            display_alternative(page, frame)
            edit.check()
            scenario_menu(frame)
            confirmations = []
            def dismiss(dialog):
                confirmations.append(dialog.message)
                dialog.dismiss()
            page.once('dialog', dismiss)
            frame.locator('#ctx-activate-alternative').click()
            assert 'current active plan will become inactive' in confirmations[0]
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current').fetchone()[0] == initial.id
            page.once('dialog', lambda dialog: dialog.accept())
            frame.locator('#ctx-activate-alternative').click()
            expect(frame.locator('.alternative-bar')).to_have_count(0)
            expect(frame.locator('.task-title', has_text='Alternative build')).to_be_visible()
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current').fetchone()[0] == alternative.id
            expect(page.get_by_test_id('stException')).to_have_count(0)
        finally:
            browser.close()
