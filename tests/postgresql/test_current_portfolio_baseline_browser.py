"""Exercise live drag, immutable baseline lanes, former tasks and project menu."""

from copy import deepcopy
import re

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
            frame.get_by_role('checkbox', name='Enable edit mode', exact=True).check(timeout=40000)
            checkbox = frame.get_by_role('checkbox', name='Show baseline', exact=True)
            expect(checkbox).not_to_be_checked(timeout=40000)
            expect(frame.locator('#frozen-row-1')).to_be_visible()
            frame.locator('#frozen-row-1').click(button='right')
            for action in ['ctx-label-add-step', 'ctx-label-edit-step', 'ctx-label-task-tags',
                           'ctx-label-task-pools', 'ctx-label-complete-step', 'ctx-label-delete-step']:
                expect(frame.locator('#' + action)).to_be_visible()
            frame.locator('#frozen-row-proj-1').click(button='right')
            for action in ['ctx-project-add-step', 'ctx-label-project-tags',
                           'ctx-label-project-pools', 'ctx-project-dependencies', 'ctx-project-log-event']:
                expect(frame.locator('#' + action)).to_be_visible()
            frame.get_by_text('Bulk actions', exact=True).hover()
            expect(frame.locator('#ctx-import-csv')).to_be_visible()
            frame.locator('#badge-projects-count').click()
            initial_height = frame.locator('#frozen-row-1').bounding_box()['height']
            expect(frame.locator('.baseline-line')).to_have_count(0)
            frame.locator('#btn-mode-day').click()
            bar = frame.locator('#timeline-row-1 .gantt-bar-wrapper')
            box = bar.bounding_box()
            project_bar = frame.locator('#timeline-row-proj-1 .project-summary-bar')
            initial_project_bar_height = project_bar.bounding_box()['height']
            initial_project_row_height = frame.locator('#frozen-row-proj-1').bounding_box()['height']
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.down()
            page.mouse.move(box['x'] + box['width'] / 2 + 76, box['y'] + box['height'] / 2, steps=8)
            page.mouse.up()
            expect(frame.locator('#frozen-row-1 .task-date-cell').first).to_have_attribute('title', '2027-01-03', timeout=15000)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT count(*) FROM eppm.project_plan WHERE project_id=1').fetchone() == (2,)
            links_before = frame.locator('#grid-links-group path').count()
            checkbox.check()
            expect(frame.locator('#timeline-row-1 .baseline-line')).to_have_attribute('title', 'Baseline: 2027-01-01 → 2027-01-05')
            former = frame.locator('#frozen-row-baseline-1--3')
            expect(former).to_contain_text('Former task')
            expect(former).to_have_class(re.compile('baseline-only'))
            assert former.locator('.task-title').evaluate('(el)=>getComputedStyle(el).color') == 'rgb(147, 51, 234)'
            assert frame.locator('#frozen-row-1').bounding_box()['height'] == pytest.approx(initial_height, abs=.1)
            assert frame.locator('#frozen-row-proj-1').bounding_box()['height'] == pytest.approx(initial_project_row_height, abs=.1)
            assert bar.bounding_box()['height'] == pytest.approx(box['height'] * .7, abs=.1)
            assert project_bar.bounding_box()['height'] == pytest.approx(initial_project_bar_height * .7, abs=.1)
            baseline_box = frame.locator('#timeline-row-1 .baseline-line').bounding_box()
            current_box = bar.bounding_box()
            assert baseline_box['y'] > current_box['y'] + current_box['height']
            expect(frame.locator('#timeline-row-baseline-1--3 .gantt-bar-wrapper')).to_have_count(0)
            expect(frame.locator('#grid-links-group path')).to_have_count(links_before)
            page.screenshot(path=str(tmp_path / 'current-portfolio-baseline.png'), full_page=True)
            checkbox.uncheck()
            expect(former).to_have_count(0)
            expect(frame.locator('.baseline-line')).to_have_count(0)
            frame.locator('#frozen-row-proj-1').click(button='right')
            dialogs = []

            def cancel_replacement(dialog):
                dialogs.append(dialog.message)
                dialog.dismiss()

            page.once('dialog', cancel_replacement)
            frame.get_by_text('Scenario management', exact=True).hover()
            frame.get_by_text('Set current project plan as baseline', exact=True).click()
            assert len(dialogs) == 1 and 'already has a baseline' in dialogs[0]
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT id FROM eppm.project_plan WHERE is_baseline').fetchone() == (baseline.id,)
                assert connection.execute('SELECT count(*) FROM eppm.project_plan WHERE project_id=1').fetchone() == (2,)
            page.once('dialog', lambda dialog: dialog.accept())
            before_revision = frame.locator('body').evaluate('() => lastDataRevision')
            frame.get_by_text('Scenario management', exact=True).hover()
            frame.get_by_text('Set current project plan as baseline', exact=True).click()
            assert frame.locator('body').evaluate('''async (_, previous) => {
                const deadline = performance.now() + 30000;
                while (lastDataRevision === previous && performance.now() < deadline) {
                    await new Promise(resolve => setTimeout(resolve, 50));
                }
                return lastDataRevision !== previous;
            }''', before_revision)
            checkbox.check()
            expect(frame.locator('#timeline-row-1 .baseline-line')).to_have_attribute('title', 'Baseline: 2027-01-03 → 2027-01-07', timeout=30000)
            expect(former).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT count(*) FROM eppm.project_plan WHERE project_id=1').fetchone() == (3,)
            assert errors == []
        finally:
            browser.close()
