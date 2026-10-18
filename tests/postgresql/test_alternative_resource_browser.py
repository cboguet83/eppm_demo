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
            frame = page.locator('iframe[title*="interactive_gantt"]').last.content_frame
            api.expect(frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]')).to_be_visible(timeout=40000)
            pool_row = frame.locator('.planning-resource-left[data-target-kind=resources][data-target-id="1"][data-scope="assigned"]')
            api.expect(pool_row).to_be_visible()
            pool_row.locator('[data-part=resource-label]').click()
            api.expect(page.get_by_role('heading', name='Active pool', exact=True)).to_be_visible(timeout=20000)
            api.expect(pool_row).to_be_visible()
            pool_row.locator('[data-part=resource-label]').dblclick()
            api.expect(pool_row).to_have_count(0)
            frame.locator('.planning-resource-left[data-target-kind=resources][data-target-id="1"][data-scope="total"] [data-part=resource-label]').dblclick()
            api.expect(pool_row).to_be_visible()
            frame.locator('[data-control=expandAll]').click()
            display_alternative(page, frame)
            rows = frame.locator('[data-part=resource-left-canvas] .planning-resource-comparison')
            api.expect(rows).to_have_count(5)
            api.expect(rows.filter(has_text='Alternative pool')).to_have_count(0)
            api.expect(frame.locator('[data-target-kind=hierarchy][data-scope="alternative_selected"]')).to_have_count(0)
            api.expect(rows.locator('[data-part=resource-branch]')).to_have_count(4)
            api.expect(frame.locator('.planning-resource-cell[data-target-kind=resources][data-target-id="2"][data-scope="alternative_total"][data-demand="3.5"]').first).to_be_visible()
            cells = frame.locator('.planning-resource-cell[data-target-kind=resources][data-target-id="2"][data-scope="alternative_selected"][data-demand="2.5"]')
            api.expect(cells.first).to_be_visible()
            api.expect(frame.locator('[data-part=resource-left-canvas] [data-target-kind=hierarchy].planning-resource-comparison [data-part=resource-label]')).to_have_css('color', 'rgb(147, 51, 234)')
            frame.locator('[data-resource-control=showTotal]').uncheck()
            api.expect(frame.locator('.planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="total"]')).to_have_count(0)
            api.expect(frame.locator('[data-part=resource-left-canvas] [data-scope="alternative_total"]')).to_have_count(0)
            api.expect(cells.first).to_be_visible()
            frame.locator('[data-resource-control=showSelected]').uncheck()
            api.expect(frame.locator('.planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="selected"]')).to_have_count(0)
            api.expect(cells).to_have_count(0)
            api.expect(frame.locator('.planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="assigned"]')).to_be_visible()
            frame.locator('[data-resource-control=showTotal]').check()
            frame.locator('[data-resource-control=showSelected]').check()
            api.expect(rows).to_have_count(5)
            container = frame.locator('[data-part=resource-left-canvas] [data-target-kind=hierarchy]').first
            api.expect(container).to_be_visible()
            api.expect(container).not_to_contain_text('Group total')
            api.expect(frame.locator('[data-part=resource-left-canvas]')).not_to_contain_text('🏊')
            api.expect(container).to_have_css('height', re.compile(r'23\.[78]\d*px'))
            warning = frame.locator('.planning-resource-cell.planning-resource-overallocated[data-target-kind=hierarchy][data-scope="alternative_total"]').first
            api.expect(warning).to_be_visible()
            assert warning.inner_text().strip() == ''
            api.expect(warning).to_have_css('background-color', 'rgb(254, 226, 226)')
            frame.locator('[data-control=collapseAll]').click()
            api.expect(frame.locator('[data-part=resource-left-canvas] .planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="total"]')).to_be_visible()
            api.expect(frame.locator('[data-part=resource-left-canvas] .planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="assigned"]')).to_be_visible()
            api.expect(frame.locator('[data-part=resource-left-canvas] .planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="assigned"] button')).to_have_count(1)
            api.expect(frame.locator('[data-part=resource-left-canvas] .planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="selected"]')).to_be_visible()
            api.expect(frame.locator('.planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="assigned"] [data-part=resource-scope]')).to_have_text('Pool capacity')
            api.expect(frame.locator('.planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="total"] [data-part=resource-scope]')).to_have_text('Pool total assignments')
            api.expect(frame.locator('.planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="selected"] [data-part=resource-scope]')).to_have_text('Assignment on filtered projects')
            api.expect(frame.locator('label:has([data-resource-control=showSelected])')).to_have_text('Assignment on filtered projects')
            api.expect(frame.locator('.planning-resource-cell[data-target-kind=resources][data-target-id="2"][data-scope="alternative_total"][data-demand="3.5"]').first).to_be_visible()
            api.expect(cells.first).to_be_visible()
            capacity_row = frame.locator('[data-part=resource-left-canvas] .planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="assigned"]')
            assert abs(capacity_row.bounding_box()['height'] - 23.8) < .1
            capacity_row.locator('button').click()
            api.expect(capacity_row).to_have_count(0)
            api.expect(frame.locator('.planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="selected"]')).to_have_count(0)
            api.expect(cells).to_have_count(0)
            frame.locator('.planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="total"] button').click()
            api.expect(cells.first).to_be_visible()
            container.dblclick()
            api.expect(frame.locator('[data-part=resource-left-canvas] .planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="total"]')).to_have_count(0)
            container.dblclick()
            api.expect(frame.locator('[data-part=resource-left-canvas] .planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="total"]')).to_be_visible()
            frame.locator('[data-control=expandAll]').click()
            api.expect(frame.locator('[data-part=resource-left-canvas] .planning-resource-left[data-target-kind=resources][data-target-id="2"][data-scope="assigned"]')).to_be_visible()
            assert frame.locator('[data-control=edit]').locator('..').evaluate('node=>node.tagName') == 'LABEL'
            api.expect(frame.locator('[data-control=edit]').locator('..')).to_contain_text('✏️ Enable edit mode')
            active_cells = frame.locator('.planning-resource-cell[data-target-kind=resources][data-target-id="1"][data-scope="total"][data-demand="1"]')
            api.expect(active_cells.first).to_be_visible()
            cells.first.click(button='right')
            api.expect(frame.locator('[data-command=show_pool_allocations]')).to_be_disabled()
            page.keyboard.press('Escape')
            frame.locator('[data-mode=Day]').click()
            page.get_by_role('button', name='Close alternative view', exact=True).click()
            api.expect(page.get_by_role('button', name='Close alternative view', exact=True)).to_have_count(0)
            api.expect(page.locator('iframe[title*="interactive_gantt"]')).to_have_count(1)
            api.expect(rows).to_have_count(0)
            api.expect(frame.locator('[data-part=resource-left-canvas]')).not_to_contain_text('Alternative pool')
            api.expect(active_cells.first).to_be_visible()
            display_alternative(page, frame)
            frame.locator('.planning-resource-cell[data-target-kind=resources][data-target-id="2"][data-scope="alternative_total"][data-demand="3.5"]').first.click(button='right')
            api.expect(frame.locator('[data-command=filter_pool]')).to_be_enabled()
            frame.locator('[data-command=filter_pool]').hover()
            frame.locator('[data-command=filter_pool_this]').click()
            api.expect(frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="2"]')).to_be_visible(timeout=20000)
            api.expect(frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]')).to_have_count(0)
        finally:
            browser.close()
