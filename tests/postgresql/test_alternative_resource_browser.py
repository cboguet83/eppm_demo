"""Alternative-only pools remain visible without changing active demand."""

from copy import deepcopy

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
        connection.execute("UPDATE eppm.project SET status='In Progress'")
        connection.execute("INSERT INTO eppm.project_task(project_plan_id,project_id,task_name,start_date,end_date) VALUES(%s,1,'Task','2027-01-01','2027-01-05')", (active.id,))
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Active pool',4),(2,'Alternative pool',4),(3,'Container',0)")
        connection.execute('UPDATE eppm.resource_pool SET parent_pool_id=3 WHERE id=2')
        connection.execute('INSERT INTO eppm.resource_pool_assignment(project_plan_id,project_id,pool_id,fte_assigned) VALUES(%s,1,1,1)', (active.id,))
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
            display_alternative(page, frame)
            rows = frame.locator('#resource-left-body .alternative-resource-row')
            api.expect(rows).to_have_count(2)
            api.expect(rows.last).to_contain_text('Alternative pool')
            cells = frame.locator('.alternative-resource-row [data-pool-id="2"][data-demand="2.5"]')
            api.expect(cells.first).to_be_visible()
            active_cells = frame.locator('[data-pool-id="1"][data-scope="total"][data-demand="1"]')
            api.expect(active_cells.first).to_be_visible()
            cells.first.click(button='right')
            api.expect(frame.locator('#ctx-pool-allocations').locator('..')).to_have_attribute('aria-disabled', 'true')
            frame.locator('#btn-mode-day').click()
            page.get_by_role('button', name='Close alternative view', exact=True).click()
            api.expect(rows).to_have_count(0)
            api.expect(frame.locator('#resource-left-body')).not_to_contain_text('Alternative pool')
            api.expect(active_cells.first).to_be_visible()
        finally:
            browser.close()
