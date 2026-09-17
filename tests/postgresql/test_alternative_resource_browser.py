"""Alternative-only pools remain visible without changing active demand."""

from copy import deepcopy
import re

import psycopg
import pytest

from app.domain.resources.models import PoolAssignment
from tests.postgresql.browser import native_server
from tests.postgresql.test_project_dependency_browser import _APP
from tests.postgresql.test_project_plans import service
from tests.postgresql.test_gantt_scenarios_browser import display_alternative

api = pytest.importorskip('playwright.sync_api')


def test_alternative_only_pool_and_container_demand_are_separate(authorized, tmp_path):
    plans = service(authorized, 4)
    active = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='In Progress' WHERE id IN (1,2)")
        connection.execute("INSERT INTO eppm.project_task(project_plan_id,project_id,task_name,start_date,end_date) VALUES(%s,1,'Task','2027-01-01','2027-01-05')", (active.id,))
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Active pool',4),(2,'Alternative pool',2),(3,'Container',0)")
        connection.execute('UPDATE eppm.resource_pool SET parent_pool_id=3 WHERE id=2')
        connection.execute('INSERT INTO eppm.resource_pool_assignment(project_plan_id,project_id,pool_id,fte_assigned) VALUES(%s,1,1,1)', (active.id,))
        connection.execute('''INSERT INTO eppm.resource_pool_assignment(project_plan_id,project_id,pool_id,fte_assigned,start_date,end_date)
            SELECT id,project_id,2,CASE WHEN project_id=2 THEN 1 ELSE 100 END,'2027-01-01','2027-01-05'
            FROM eppm.project_plan WHERE is_current AND project_id IN (2,3)''')
    active = plans.list_plans(1)[0]
    content = deepcopy(active.content)
    content.assignments = [PoolAssignment(2, 1, 2.5, task_id=content.tasks[0]['id'])]
    plans.save(1, active.id, active.revision, 'Option A', content)
    with native_server(authorized, tmp_path, _APP) as server, api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width':1700, 'height':1200})
            page.goto(server.origin)
            frame = page.frame_locator('iframe[title*="interactive_gantt"]')
            api.expect(frame.locator('#frozen-row-proj-1')).to_be_visible(timeout=40000)
            frame.locator('#btn-expand-all').click()
            display_alternative(page, frame)
            rows = frame.locator('#resource-left-body .alternative-resource-row')
            api.expect(rows).to_have_count(5)
            api.expect(rows.filter(has_text='Alternative pool')).to_have_count(0)
            api.expect(frame.locator('.resource-group-row[data-scope="alternative_selected"]')).to_have_count(0)
            api.expect(rows.locator('.resource-tree-branch')).to_have_count(4)
            api.expect(frame.locator('[data-pool-id="2"][data-scope="alternative_total"][data-demand="3.5"]').first).to_be_visible()
            cells = frame.locator('[data-pool-id="2"][data-scope="alternative_selected"][data-demand="2.5"]')
            api.expect(cells.first).to_be_visible()
            api.expect(frame.locator('#resource-left-body .resource-group-row.alternative-resource-row .r-name-text')).to_have_css('color', 'rgb(147, 51, 234)')
            frame.locator('#chk-show-total-demand').uncheck()
            api.expect(frame.locator('[data-row-id="pool-2-total"]')).to_have_count(0)
            api.expect(frame.locator('#resource-left-body [data-scope="alternative_total"]')).to_have_count(0)
            api.expect(cells.first).to_be_visible()
            frame.locator('#chk-show-selected-demand').uncheck()
            api.expect(frame.locator('[data-row-id="pool-2-selected"]')).to_have_count(0)
            api.expect(cells).to_have_count(0)
            api.expect(frame.locator('[data-row-id="pool-2-assigned"]')).to_be_visible()
            frame.locator('#chk-show-total-demand').check()
            frame.locator('#chk-show-selected-demand').check()
            api.expect(rows).to_have_count(5)
            container = frame.locator('#resource-left-body .resource-group-row').first
            api.expect(container).to_be_visible()
            api.expect(container).not_to_contain_text('Group total')
            api.expect(frame.locator('#resource-left-body')).not_to_contain_text('🏊')
            api.expect(container).to_have_css('height', re.compile(r'23\.[78]\d*px'))
            warning = frame.locator('.resource-group-cell.cell-overallocated[data-scope="alternative_total"]').first
            api.expect(warning).to_be_visible()
            assert warning.inner_text().strip() == ''
            api.expect(warning).to_have_css('background-color', 'rgb(254, 226, 226)')
            frame.locator('#btn-collapse-all').click()
            api.expect(frame.locator('#resource-left-body [data-row-id="pool-2-total"]')).to_be_visible()
            api.expect(frame.locator('#resource-left-body [data-row-id="pool-2-assigned"]')).to_be_visible()
            api.expect(frame.locator('#resource-left-body [data-row-id="pool-2-assigned"] button')).to_have_count(1)
            api.expect(frame.locator('#resource-left-body [data-row-id="pool-2-selected"]')).to_be_visible()
            api.expect(frame.locator('[data-row-id="pool-2-assigned"] .assigned-badge')).to_have_text('Pool capacity')
            api.expect(frame.locator('[data-row-id="pool-2-total"] .total-badge')).to_have_text('Pool total assignments')
            api.expect(frame.locator('[data-row-id="pool-2-selected"] .scope-badge')).to_have_text('Assignment on filtered projects')
            api.expect(frame.locator('#lbl-show-selected')).to_have_text('Assignment on filtered projects')
            api.expect(frame.locator('[data-pool-id="2"][data-scope="alternative_total"][data-demand="3.5"]').first).to_be_visible()
            api.expect(cells.first).to_be_visible()
            capacity_row = frame.locator('#resource-left-body [data-row-id="pool-2-assigned"]')
            assert abs(capacity_row.bounding_box()['height'] - 23.8) < .1
            capacity_row.locator('button').click()
            api.expect(capacity_row).to_have_count(0)
            api.expect(frame.locator('[data-row-id="pool-2-selected"]')).to_have_count(0)
            api.expect(cells).to_have_count(0)
            frame.locator('[data-row-id="pool-2-total"] button').click()
            api.expect(cells.first).to_be_visible()
            container.dblclick()
            api.expect(frame.locator('#resource-left-body [data-row-id="pool-2-total"]')).to_have_count(0)
            container.dblclick()
            api.expect(frame.locator('#resource-left-body [data-row-id="pool-2-total"]')).to_be_visible()
            frame.locator('#btn-expand-all').click()
            api.expect(frame.locator('#resource-left-body [data-row-id="pool-2-assigned"]')).to_be_visible()
            api.expect(frame.locator('#enable-edit').locator('..')).to_have_class('toggle-link-opt')
            api.expect(frame.locator('#enable-edit').locator('..')).to_contain_text('✏️ Enable edit mode')
            active_cells = frame.locator('[data-pool-id="1"][data-scope="total"][data-demand="1"]')
            api.expect(active_cells.first).to_be_visible()
            cells.first.click(button='right')
            api.expect(frame.locator('#ctx-pool-allocations').locator('..')).to_have_attribute('aria-disabled', 'true')
            frame.locator('#btn-mode-day').click()
            page.get_by_role('button', name='Close alternative view', exact=True).click()
            api.expect(rows).to_have_count(0)
            api.expect(frame.locator('#resource-left-body')).not_to_contain_text('Alternative pool')
            api.expect(active_cells.first).to_be_visible()
            display_alternative(page, frame)
            frame.locator('[data-pool-id="2"][data-scope="alternative_total"][data-demand="3.5"]').first.click(button='right')
            api.expect(frame.locator('#ctx-res-filter-btn')).to_have_attribute('aria-disabled', 'false')
            frame.locator('#ctx-res-filter-btn').hover()
            frame.locator('[data-resource-filter="consuming"]').click()
            api.expect(frame.locator('#frozen-row-proj-2')).to_be_visible(timeout=20000)
            api.expect(frame.locator('#frozen-row-proj-1')).to_have_count(0)
        finally:
            browser.close()
