"""The same filter panel scopes dashboard, project grid, and Gantt after navigation."""

import psycopg
from pathlib import Path

from tests.postgresql.browser import native_server
from tests.postgresql.dashboard_browser import _SCREEN
from tests.test_dialog_browser import expect, sync_playwright


_APP = _SCREEN[:_SCREEN.index("if st.session_state.get('nav_redirect'):")] + '''
from app.main import create_project_workspace, create_planning_workspace
from app.presentation.pages.portfolio import render_portfolio_overview
from app.presentation.pages.planning import render_planning_milestones
access = BusinessAccess(actor, authentication.policy)
view = st.radio('View', ['Dashboard', 'Projects', 'Planning', 'Other'], horizontal=True)
if view == 'Dashboard':
    render_dashboard(service)
elif view == 'Projects':
    render_portfolio_overview(create_project_workspace(resources, access=access))
elif view == 'Planning':
    render_planning_milestones(create_planning_workspace(resources, access=access))
'''


def test_organization_frames_preserve_state_and_highlight_collapsed_filters(authorized, tmp_path):
    with native_server(authorized, tmp_path, _APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1600, 'height': 1200})
            page.goto(server.origin)
            for facet in ('division', 'org_team', 'org_manager'):
                frame = page.locator('.st-key-organization_frame_' + facet)
                expect(frame.locator('summary')).to_be_visible(timeout=30000)
                frame.locator('summary').click()
                frame.get_by_role('button').first.click()
                frame.locator('summary').click()
                expect(frame.locator('summary')).to_have_css('background-color', 'rgb(196, 16, 57)')
            team = page.locator('.st-key-organization_frame_org_team')
            team.locator('summary').click()
            for view in ('Other', 'Projects', 'Planning', 'Dashboard'):
                page.get_by_test_id('stRadio').get_by_text(view, exact=True).click()
                if view == 'Other':
                    expect(team).to_have_count(0)
                    continue
                expect(team.locator('details')).to_have_attribute('open', '')
                for facet in ('division', 'org_manager'):
                    summary = page.locator('.st-key-organization_frame_' + facet + ' summary')
                    expect(summary).to_have_css('background-color', 'rgb(196, 16, 57)')
                expect(page.get_by_test_id('stException')).to_have_count(0)
            page.screenshot(path=str(Path('.local/organization-frame-state.png').resolve()))
        finally:
            browser.close()


def test_shared_status_filter_survives_navigation_and_widget_cleanup(authorized, tmp_path):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='Project '||id, status=CASE id WHEN 1 THEN 'Completed' ELSE 'In Progress' END")
        connection.execute("INSERT INTO eppm.project_task(project_id,project_plan_id,task_name,start_date,end_date) SELECT id,(SELECT id FROM eppm.project_plan WHERE project_id=p.id AND is_current),'Task '||id,'2026-01-01','2026-02-01' FROM eppm.project p")
    with native_server(authorized, tmp_path, _APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1600, 'height': 1200})
            page.goto(server.origin)
            status = page.locator('.st-key-dashboard_filter_status').last
            expect(status).to_contain_text('In Progress', timeout=30000)
            status.get_by_role('button').click()
            page.locator('.st-key-dashboard_filter_status_option_Completed label').click()
            expect(status).to_contain_text('Completed')
            page.locator('[class*="st-key-dashboard_filter_status_option_In"] label').click()
            expect(status).not_to_contain_text('In Progress')
            page.keyboard.press('Escape')
            for view in ('Other', 'Projects', 'Planning', 'Dashboard'):
                page.get_by_test_id('stRadio').get_by_text(view, exact=True).click()
                if view == 'Other':
                    expect(status).to_have_count(0)
                    continue
                if view == 'Dashboard':
                    expect(page.locator('.st-key-dashboard_finance_chart')).to_be_visible()
                expect(status).to_contain_text('Completed')
                expect(status).not_to_contain_text('In Progress')
                if view == 'Projects':
                    rows = page.locator('.st-key-portfolio_master_table tbody tr[data-project-id]')
                    expect(rows).to_have_count(1)
                    expect(rows.first).to_have_attribute('data-project-id', '1')
                if view == 'Planning':
                    project_button = page.locator('.st-key-planning_project_filter_slot button')
                    project_box = project_button.bounding_box()
                    status_box = status.get_by_role('button').bounding_box()
                    assert abs(project_box['y'] - status_box['y']) < 1
                    assert project_box['x'] < status_box['x']
                    page.locator('.st-key-planning_project_filter_slot button').click()
                    selection = page.locator('.st-key-ms_multi_projects')
                    expect(selection).to_contain_text('1 projects found')
                    page.keyboard.press('Escape')
                    expect(page.locator('iframe[title*="interactive_gantt"]')).to_be_visible(timeout=30000)
                    expect(page.locator('.st-key-portfolio_master_table')).to_have_count(0)
                manager_box = page.locator('.st-key-organization_filter_frames details').last.bounding_box()
                status_box = status.get_by_role('button').bounding_box()
                reset_box = page.locator('.st-key-dashboard_clear button').bounding_box()
                assert abs(status_box['height'] - manager_box['height']) < 1
                assert abs(reset_box['height'] - manager_box['height']) < 1
                assert abs(status_box['y'] - manager_box['y'] - manager_box['height'] - 8) < 1
                assert float(page.get_by_test_id('stMainBlockContainer').evaluate(
                    'node => parseFloat(getComputedStyle(node).paddingTop)')) < 1
                if view == 'Projects':
                    create_box = page.locator('.st-key-btn_create_project_from_portfolio button').bounding_box()
                    assert abs(create_box['x'] + create_box['width'] - reset_box['x'] - reset_box['width']) < 1
                page.screenshot(path=str(Path(f'.local/shared-filters-{view.lower()}.png').resolve()), full_page=True)
                expect(page.get_by_test_id('stException')).to_have_count(0)
            page.locator('.st-key-dashboard_clear button').click()
            expect(status).to_contain_text('In Progress')
            page.get_by_test_id('stRadio').get_by_text('Projects', exact=True).click()
            expect(status).to_contain_text('In Progress')
            expect(page.locator('.st-key-portfolio_master_table tbody tr[data-project-id="1"]')).to_have_count(0)
        finally:
            browser.close()
