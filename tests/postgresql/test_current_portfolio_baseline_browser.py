"""Exercise live drag, immutable baseline lanes, former tasks and project menu."""

import re
from time import monotonic, sleep

import psycopg
import pytest

from tests.postgresql.browser import native_server
from tests.postgresql.test_project_dependency_browser import _APP
from tests.postgresql.test_project_plans import service

api = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = api.expect, api.sync_playwright


def test_current_portfolio_drag_and_baseline_overlay(authorized, tmp_path):
    plans = service(authorized, 4)
    initial = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='In Progress'")
        connection.execute("INSERT INTO eppm.project_task(project_plan_id,project_id,task_name,start_date,end_date) VALUES(%s,1,'Build','2027-01-01','2027-01-05'),(%s,1,'Ship','2027-01-06','2027-01-08'),(%s,1,'Former task','2027-01-09','2027-01-10')", (initial.id, initial.id, initial.id))
        connection.execute('INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES(2,1),(3,2)')
    baseline = plans.baseline_current(1)
    from app.application.services.planning import PlanningService
    from app.infrastructure.postgresql.planning import PostgresPlanningGateway
    planning = PlanningService(PostgresPlanningGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    planning.delete_milestone(3)
    with native_server(authorized, tmp_path, _APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1700, 'height': 1200})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(server.origin)
            frame = page.frame_locator('iframe[title*="interactive_gantt"]')
            frame.get_by_role(
                'checkbox', name=re.compile('Enable edit mode'),
            ).check(timeout=40000)
            frame.locator('body').evaluate("""() => {
                window.observedPlanningRevision=null;
                addEventListener('message',event=>{if(event.data?.type==='streamlit:render' && event.data.args?.data_revision)
                    window.observedPlanningRevision=event.data.args.data_revision;});
            }""")
            expect(frame.get_by_role('checkbox', name='Show baseline', exact=True)).to_have_count(0)
            expect(frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="1"][data-lane=current]')).to_be_visible()
            frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="1"][data-lane=current]').click(button='right')
            expect(frame.get_by_role('menuitem', name='Edit', exact=True)).to_be_visible()
            for action in ['add_step_after', 'manage_task_tags', 'manage_task_pools', 'complete_step', 'delete_step']:
                expect(frame.locator('[data-command=' + action + ']')).to_be_visible()
            page.keyboard.press('Escape')
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
            for action in ['add_step', 'manage_project_tags', 'manage_project_pools', 'project_dependencies', 'log_project_event']:
                expect(frame.locator('[data-command=' + action + ']')).to_be_visible()
            frame.get_by_role('menuitem', name='Bulk actions', exact=False).hover()
            expect(frame.locator('[data-command=import_csv_template]')).to_be_visible()
            page.keyboard.press('Escape')
            page.keyboard.press('Escape')
            initial_height = frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="1"][data-lane=current]').bounding_box()['height']
            expect(frame.locator('.planning-bar[data-lane=baseline]')).to_have_count(0)
            frame.locator('[data-mode=Day]').click()
            bar = frame.locator('.planning-bar[data-target-kind=tasks][data-target-id="1"][data-lane=current]')
            box = bar.bounding_box()
            project_bar = frame.locator('.planning-bar[data-target-kind=projects][data-lane=current]')
            initial_project_bar_height = project_bar.bounding_box()['height']
            initial_project_row_height = frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').bounding_box()['height']
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.down()
            page.mouse.move(box['x'] + box['width'] / 2 + 76, box['y'] + box['height'] / 2, steps=8)
            page.mouse.up()
            expect(frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="1"] .planning-column-start').first).to_have_text('2027-01-03', timeout=15000)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT count(*) FROM eppm.project_plan WHERE project_id=1').fetchone() == (2,)
            links_before = frame.locator('[data-part=dependencies] path').count()
            page.keyboard.press('Escape')
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
            frame.get_by_role('menuitem', name='Scenario management', exact=False).hover()
            frame.locator('[data-command=show_baseline]').click()
            expect(frame.locator('.planning-bar[data-target-kind=tasks][data-target-id="1"][data-lane=baseline]')).to_have_attribute('data-schedule-label', '2027-01-01 → 2027-01-05')
            former = frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="-3"][data-lane=baseline]')
            expect(former).to_contain_text('Former task')
            expect(former).to_have_attribute('data-lane', 'baseline')
            assert former.locator('.planning-column-name').evaluate('(el)=>getComputedStyle(el).color') == 'rgb(147, 51, 234)'
            assert frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="1"][data-lane=current]').bounding_box()['height'] == pytest.approx(initial_height, abs=.1)
            assert frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').bounding_box()['height'] == pytest.approx(initial_project_row_height, abs=.1)
            assert bar.bounding_box()['height'] == pytest.approx(box['height'] * .7, abs=.1)
            assert project_bar.bounding_box()['height'] == pytest.approx(initial_project_bar_height * .7, abs=.1)
            baseline_box = frame.locator('.planning-bar[data-target-kind=tasks][data-target-id="1"][data-lane=baseline]').bounding_box()
            current_box = bar.bounding_box()
            assert baseline_box['y'] > current_box['y'] + current_box['height']
            expect(frame.locator('.planning-bar[data-target-kind=tasks][data-target-id="-3"][data-lane=current]')).to_have_count(0)
            expect(frame.locator('[data-part=dependencies] path')).to_have_count(links_before)
            page.screenshot(path=str(tmp_path / 'current-portfolio-baseline.png'), full_page=True)
            page.keyboard.press('Escape')
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
            frame.get_by_role('menuitem', name='Scenario management', exact=False).hover()
            frame.locator('[data-command=hide_baseline]').click()
            expect(former).to_have_count(0)
            expect(frame.locator('.planning-bar[data-lane=baseline]')).to_have_count(0)
            page.keyboard.press('Escape')
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
            dialogs = []

            def cancel_replacement(dialog):
                dialogs.append(dialog.message)
                dialog.dismiss()

            page.once('dialog', cancel_replacement)
            frame.get_by_role('menuitem', name='Scenario management', exact=False).hover()
            frame.get_by_text('Set current project as baseline', exact=True).click()
            assert len(dialogs) == 1 and 'already has a baseline' in dialogs[0]
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT id FROM eppm.project_plan WHERE is_baseline').fetchone() == (baseline.id,)
                assert connection.execute('SELECT count(*) FROM eppm.project_plan WHERE project_id=1').fetchone() == (2,)
            before_revision = frame.locator('body').evaluate('()=>window.observedPlanningRevision')
            page.once('dialog', lambda dialog: dialog.accept())
            frame.get_by_role('menuitem', name='Scenario management', exact=False).hover()
            frame.get_by_text('Set current project as baseline', exact=True).click()
            deadline = monotonic() + 30
            while monotonic() < deadline:
                with psycopg.connect(authorized.setup.operator_url) as connection:
                    count = connection.execute('SELECT count(*) FROM eppm.project_plan WHERE project_id=1').fetchone()[0]
                if count == 3:
                    break
                sleep(.05)
            assert count == 3, 'Confirmed replacement must create the new saved baseline'
            assert frame.locator('body').evaluate("""async (_, previous) => {
                const deadline=performance.now()+30000;
                while(window.observedPlanningRevision===previous && performance.now()<deadline)
                    await new Promise(resolve=>setTimeout(resolve,50));
                return window.observedPlanningRevision!==previous;
            }""", before_revision)
            page.keyboard.press('Escape')
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
            frame.get_by_role('menuitem', name='Scenario management', exact=False).hover()
            frame.locator('[data-command=show_baseline]').click()
            expect(frame.locator('.planning-bar[data-target-kind=tasks][data-target-id="1"][data-lane=baseline]')).to_have_attribute('data-schedule-label', '2027-01-03 → 2027-01-07', timeout=30000)
            expect(former).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT count(*) FROM eppm.project_plan WHERE project_id=1').fetchone() == (3,)
            assert errors == []
        finally:
            browser.close()
