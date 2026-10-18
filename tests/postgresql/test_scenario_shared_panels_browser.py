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
            expect(frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="1"]')).to_be_visible(timeout=40000)
            display_alternative(page, frame)
            frame.locator('[data-mode=Day]').click()
            bar = frame.locator('.planning-bar[data-target-kind=tasks][data-target-id="1"][data-lane=alternative]')
            bar.hover()
            tooltip = frame.locator('[role=tooltip]')
            for text in ['Scenario: Option A', 'Alternative build', 'Scenario description', '65%', 'Scenario tag', 'Engineers', '1.25 FTE']:
                expect(tooltip).to_contain_text(text)
            page.screenshot(path=str(tmp_path / 'shared-scenario-tooltip.png'), full_page=True)
            frame.locator('.planning-bar[data-target-kind=tasks][data-target-id="1"][data-lane=current]').hover()
            expect(tooltip).not_to_contain_text('Scenario description')
            expect(tooltip).to_contain_text(f'Scenario: {active.name}')
            frame.locator('.planning-bar[data-target-kind=projects][data-lane=alternative]').hover()
            expect(tooltip).to_contain_text('Scenario: Option A')
            frame.locator('.planning-bar[data-target-kind=projects][data-lane=current]').hover()
            expect(tooltip).to_contain_text(f'Scenario: {active.name}')
            expect(frame.locator('[data-task-count=current]')).to_have_attribute('title', f'Tasks in {active.name}')
            expect(frame.locator('[data-task-count=alternative]')).to_have_attribute('title', 'Tasks in Option A')
            frame.get_by_role('checkbox', name=re.compile('Enable edit mode')).check()
            page.keyboard.press('Escape')
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
            frame.locator('[data-command=project_dependencies]').click()
            expect(frame.locator('[data-part=project-dependency-editor] h3')).to_have_text('Manage dependencies — Editable')
            expect(frame.locator('[data-part=project-dependency-editor] [data-field=name]')).to_be_hidden()
            frame.locator('[data-part=project-dependency-editor] button:has-text("Add predecessor")').click()
            frame.locator('[data-part=project-dependency-editor] [data-choice-project]').select_option('2')
            frame.locator('[data-part=project-dependency-editor] [data-field=type]').select_option('SS')
            frame.locator('[data-part=project-dependency-editor] [data-field=lagDays]').fill('-3')
            frame.locator('[data-part=project-dependency-editor] button[type=submit]').click()
            expect(frame.locator('[data-part=project-dependency-editor]')).to_be_hidden(timeout=15000)
            expect(bar).to_have_attribute('data-plan-revision', str(alternative.revision + 1))
            page.keyboard.press('Escape')
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
            frame.locator('[data-command=project_dependencies]').click()
            expect(frame.locator('[data-part=project-dependency-editor] [data-field=lagDays]')).to_have_value('-3')
            frame.locator('[data-part=project-dependency-editor] [data-field=lagDays]').fill('4')
            with psycopg.connect(authorized.setup.operator_url) as connection:
                connection.execute('UPDATE eppm.project_plan SET revision=revision+1 WHERE id=%s', (alternative.id,))
            frame.locator('[data-part=project-dependency-editor] button[type=submit]').click()
            expect(frame.locator('[data-part=project-dependency-editor] [role=alert]')).to_contain_text('changed', timeout=15000)
            expect(frame.locator('[data-part=project-dependency-editor] [data-field=lagDays]')).to_have_value('4')
            frame.locator('[data-part=project-dependency-editor] button:has-text("Reload dependencies")').click()
            expect(frame.locator('[data-part=project-dependency-editor] [data-field=lagDays]')).to_have_value('-3')
            frame.locator('[data-part=project-dependency-editor] button:has-text("Remove")').click()
            frame.locator('[data-part=project-dependency-editor] button[type=submit]').click()
            expect(frame.locator('[data-part=project-dependency-editor]')).to_be_hidden(timeout=15000)
            frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="1"]').click(button='right')
            frame.locator('[data-command=manage_task_tags]').click()
            expect(page.get_by_role('dialog')).to_contain_text('Manage Task Tags')
            expect(page.get_by_role('dialog')).to_contain_text('Scenario tag')
            page.locator('.st-key-ti_attach_task_free_tag input').fill('Added through shared form')
            page.locator('.st-key-btn_confirm_attach_task_tag button').click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            bar.hover()
            expect(tooltip).to_contain_text('Added through shared form')
            page.keyboard.press('Escape')
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
            frame.locator('[data-command=edit_project_details]').click()
            expect(page.get_by_role('dialog')).to_contain_text('Project details')
            expect(page.get_by_role('dialog').get_by_role('button', name='Edit project', exact=True)).to_have_count(0)
            page.get_by_role('dialog').get_by_role('button', name='Close', exact=True).click()
            page.keyboard.press('Escape')
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
            frame.locator('[data-command=bulk_actions]').hover()
            with page.expect_download() as download:
                frame.locator('[data-command=export_csv_template]').click()
            path = tmp_path / 'alternative.csv'
            download.value.save_as(path)
            assert 'Alternative build' in path.read_text(encoding='utf-8-sig')
            expect(page.locator('iframe[title*="interactive_gantt"]')).to_have_count(1)
            page.keyboard.press('Escape')
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
            frame.locator('[data-command=bulk_actions]').hover()
            frame.locator('[data-command=import_csv_template]').click()
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
            expect(frame.locator('.planning-bar[data-target-kind=tasks][data-target-id="1"][data-lane=alternative]')).to_be_visible()
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
