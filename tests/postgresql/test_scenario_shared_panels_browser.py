"""Alternative scenarios use the same panels and tooltip rendering as active plans."""

from copy import deepcopy
import re

import psycopg
import pytest

from app.domain.resources.models import PoolAssignment
from app.infrastructure.postgresql.plan_rows import read_plans
from tests.postgresql.browser import native_server
from tests.postgresql.test_gantt_scenarios_browser import display_alternative
from tests.postgresql.test_project_dependency_browser import _APP
from tests.postgresql.test_project_plans import service

api = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = api.expect, api.sync_playwright


def test_alternative_tooltips_project_dependencies_tags_and_csv_reuse_shared_panels(authorized, tmp_path):
    plans = service(authorized, 4)
    active = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='In Progress'")
        connection.execute("INSERT INTO eppm.project_task(project_id,project_plan_id,task_name,start_date,end_date) VALUES(1,%s,'Build','2027-01-01','2027-01-05')", (active.id,))
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Engineers',2)")
    active = next(plan for plan in plans.list_plans(1) if plan.is_current)
    content = deepcopy(active.content)
    content.tasks[0].update(task_name='Alternative build', description='Scenario description', progress_pct=65)
    content.task_tags[1] = [dict(tag_id=None, free_tag='Scenario tag')]
    content.assignments = [PoolAssignment(1, 1, 1.25, task_id=1)]
    alternative = plans.save(1, active.id, active.revision, 'Option A', content)
    with native_server(authorized, tmp_path, _APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width':1700, 'height':1200})
            page.goto(server.origin)
            frame = page.frame_locator('iframe[title*="interactive_gantt"]')
            expect(frame.locator('#frozen-row-1')).to_be_visible(timeout=40000)
            display_alternative(page, frame)
            frame.locator('#btn-mode-day').click()
            bar = frame.locator('#timeline-row-1 .alternative-bar')
            bar.hover()
            tooltip = frame.locator('#gantt-tooltip')
            for text in ['Scenario: Option A', 'Alternative build', 'Scenario description', '65%', 'Scenario tag', 'Engineers', '1.25 FTE']:
                expect(tooltip).to_contain_text(text)
            page.screenshot(path=str(tmp_path / 'shared-scenario-tooltip.png'), full_page=True)
            frame.locator('#timeline-row-1 .gantt-bar-wrapper').hover()
            expect(tooltip).not_to_contain_text('Scenario description')
            expect(tooltip).to_contain_text(f'Scenario: {active.name}')
            frame.locator('#timeline-row-proj-1 .project-alternative').hover()
            expect(tooltip).to_contain_text('Scenario: Option A')
            frame.locator('#timeline-row-proj-1 .project-summary-bar').hover()
            expect(tooltip).to_contain_text(f'Scenario: {active.name}')
            expect(frame.locator('.project-group-count')).to_have_attribute('title', f'Tasks in {active.name}')
            expect(frame.locator('.alternative-project-count')).to_have_attribute('title', 'Tasks in Option A')
            frame.get_by_role('checkbox', name=re.compile('Enable edit mode')).check()
            frame.locator('#frozen-row-proj-1').click(button='right')
            frame.locator('#ctx-project-dependencies').click()
            expect(frame.locator('#modal-title-header')).to_have_text('Manage dependencies — Editable')
            expect(frame.locator('#modal-task-name')).to_be_hidden()
            frame.locator('#modal-btn-add-dep').click()
            frame.locator('.dep-proj').select_option('2')
            frame.locator('.dep-type').select_option('SS')
            frame.locator('.dep-lag').fill('-3')
            frame.locator('#modal-btn-save').click()
            expect(frame.locator('#modal-backdrop')).to_be_hidden(timeout=15000)
            expect(bar).to_have_attribute('data-plan-revision', str(alternative.revision + 1))
            frame.locator('#frozen-row-proj-1').click(button='right')
            frame.locator('#ctx-project-dependencies').click()
            expect(frame.locator('.dep-lag')).to_have_value('-3')
            frame.locator('.dep-lag').fill('4')
            with psycopg.connect(authorized.setup.operator_url) as connection:
                connection.execute('UPDATE eppm.project_plan SET revision=revision+1 WHERE id=%s', (alternative.id,))
            frame.locator('#modal-btn-save').click()
            expect(frame.locator('#project-dependency-status')).to_contain_text('changed', timeout=15000)
            expect(frame.locator('.dep-lag')).to_have_value('4')
            frame.locator('#project-dependency-reload').click()
            expect(frame.locator('.dep-lag')).to_have_value('-3')
            frame.locator('.btn-remove-dep').click()
            frame.locator('#modal-btn-save').click()
            expect(frame.locator('#modal-backdrop')).to_be_hidden(timeout=15000)
            frame.locator('#frozen-row-1').click(button='right')
            frame.locator('#ctx-label-task-tags').click()
            expect(page.get_by_role('dialog')).to_contain_text('Manage Task Tags')
            expect(page.get_by_role('dialog')).to_contain_text('Scenario tag')
            page.locator('.st-key-ti_attach_task_free_tag input').fill('Added through shared form')
            page.locator('.st-key-btn_confirm_attach_task_tag button').click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            bar.hover()
            expect(tooltip).to_contain_text('Added through shared form')
            frame.locator('#frozen-row-proj-1').click(button='right')
            frame.locator('#ctx-label-edit-project').click()
            expect(page.get_by_role('dialog')).to_contain_text('Project details')
            expect(page.get_by_role('dialog').get_by_role('button', name='Edit project', exact=True)).to_have_count(0)
            page.get_by_role('dialog').get_by_role('button', name='Close', exact=True).click()
            frame.locator('#frozen-row-proj-1').click(button='right')
            frame.locator('#ctx-bulk-actions').hover()
            with page.expect_download() as download:
                frame.locator('#ctx-export-csv').click()
            path = tmp_path / 'alternative.csv'
            download.value.save_as(path)
            assert 'Alternative build' in path.read_text(encoding='utf-8-sig')
            expect(page.locator('iframe[title*="interactive_gantt"]')).to_have_count(1)
            frame.locator('#frozen-row-proj-1').click(button='right')
            frame.locator('#ctx-bulk-actions').hover()
            frame.locator('#ctx-import-csv').click()
            expect(page.get_by_role('dialog')).to_contain_text('Schedule CSV')
            page.locator('input[type=file]').set_input_files(dict(name='replacement.csv', mimeType='text/csv',
                buffer=b'step_number,task_name,start_date,end_date\n1,Imported scenario,9/20/2025,10/1/2026\n'))
            expect(page.get_by_role('button', name='Import plan revision', exact=True)).to_be_disabled()
            page.get_by_role('textbox', name='Version name', exact=True).fill('CSV revision')
            page.get_by_role('textbox', name='Version name', exact=True).press('Tab')
            expect(page.get_by_role('checkbox', name='Set import as the active plan')).not_to_be_checked()
            expect(page.get_by_role('checkbox', name='Set import as the active plan')).to_be_disabled()
            page.get_by_role('button', name='Import plan revision', exact=True).click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            expect(page.get_by_text('Import successful. Imported scenario is now available in the scenarios list.', exact=True)).to_be_visible()
            expect(frame.locator('#timeline-row-1 .alternative-bar')).to_be_visible()
            with psycopg.connect(authorized.setup.operator_url) as connection:
                saved = read_plans(connection, [active.id, alternative.id])
            assert saved[active.id] == active.content
            assert saved[alternative.id].tasks[0]['task_name'] == 'Alternative build'
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute("SELECT name,s.code FROM eppm.project_plan p JOIN eppm.plan_status s ON s.id=p.status_id WHERE p.project_id=1 AND p.name='CSV revision' AND NOT is_current").fetchone() == ('CSV revision', 'draft')
                imported_id = connection.execute("SELECT id FROM eppm.project_plan WHERE project_id=1 AND name='CSV revision'").fetchone()[0]
                imported = read_plans(connection, [imported_id])[imported_id].tasks[0]
                assert (imported['start_date'], imported['end_date']) == ('2025-09-20', '2026-10-01')
        finally:
            browser.close()
