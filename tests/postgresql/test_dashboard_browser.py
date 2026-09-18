"""Real dashboard charts, issue popup, paging and browser-local session activity."""

import json
import re
import time

import pytest

from tests.test_dialog_browser import expect, sync_playwright
from tests.postgresql.dashboard_browser import popup_server


@pytest.mark.parametrize('popup_server', ['shared-budget'], indirect=True, ids=['distinct-budget-shares'])
def test_finance_curve_uses_selected_project_share(popup_server):
    """Check actual chart values when two projects share one approved WBS."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = popup_server.new_page(browser, viewport={'width':1500,'height':1200})
            page.goto(popup_server.origin)
            page.locator('.st-key-dashboard_project_list summary').click(timeout=30000)
            table = page.locator('.st-key-dashboard_project_table .viewport')
            expect(table.locator('tr[data-project-id="1"]')).to_be_visible(timeout=30000)
            points = page.locator('.st-key-dashboard_finance_chart circle')
            for project_id, expected in [(1,'0.05 kEUR'),(2,'0.03 kEUR')]:
                table.locator(f'tr[data-project-id="{project_id}"]').click()
                expect(page.get_by_text('1 matching projects',exact=True)).to_be_visible()
                expect(points).to_have_count(2)
                expect(points.first).to_have_attribute('aria-label', re.compile(': '+re.escape(expected)))
                points.first.hover()
                expect(page.locator('.st-key-dashboard_finance_chart .tip')).to_contain_text(expected)
                table.locator(f'tr[data-project-id="{project_id}"]').click()
                expect(page.get_by_text('1000 matching projects',exact=True)).to_be_visible()
            expect(page.get_by_text('Shell runs: 1',exact=True)).to_be_visible()
        finally:
            browser.close()


@pytest.mark.parametrize('popup_server', ['dashboard'], indirect=True, ids=['dashboard-1000'])
def test_dashboard_charts_paging_and_read_only_issues_do_not_rerun_shell(popup_server,tmp_path):
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        try:
            page=popup_server.new_page(browser, viewport={'width':1500,'height':1200})
            browser_errors = []
            page.on('pageerror', lambda error: browser_errors.append(str(error)))
            start=time.perf_counter();page.goto(popup_server.origin)
            expect(page.locator('.st-key-dashboard_issue_count button:visible')).to_be_visible(timeout=30000)
            expect(page.locator('.st-key-dashboard_finance_chart').first).to_be_visible(timeout=30000)
            initial=time.perf_counter()-start
            expect(page.get_by_text('1000 matching projects',exact=True)).to_be_visible()
            expect(page.locator('.st-key-dashboard_project_list details')).not_to_have_attribute('open', '')
            page.locator('.st-key-dashboard_project_list summary').click()
            table=page.locator('.st-key-dashboard_project_table .viewport')
            expect(table.locator('tr[data-project-id="1"]')).to_be_visible()
            assert table.locator('tr[data-project-id]').count()<=12
            table.locator('tr[data-project-id="2"]').click()
            expect(page.get_by_text('1 matching projects',exact=True)).to_be_visible()
            expect(table.locator('tr[data-project-id="2"]')).to_have_attribute('aria-selected','true')
            expect(page.locator('.st-key-dashboard_issue_count button:visible')).to_be_disabled()
            expect(page.locator('.st-key-dashboard_issue_card')).to_contain_text('0 Active Issue')
            expect(page.get_by_text('0 Active Issue',exact=True)).to_have_css('color','rgb(0, 0, 0)')
            expect(page.locator('.st-key-dashboard_issue_count [data-testid=stIconMaterial]').first).to_have_css('color','rgb(35, 147, 76)')
            expect(page.get_by_role('dialog')).to_have_count(0)
            expect(page.locator('.st-key-dashboard_finance_chart circle')).to_have_count(0)
            expect(page.get_by_text('Shell runs: 1',exact=True)).to_be_visible()
            table.locator('tr[data-project-id="2"]').press('Enter')
            expect(page.get_by_text('1000 matching projects',exact=True)).to_be_visible()
            expect(page.locator('.st-key-dashboard_issue_count button:visible')).to_be_enabled()
            expect(page.locator('.st-key-dashboard_issue_card')).to_contain_text('1 Active Issue')
            expect(page.get_by_text('1 Active Issue',exact=True)).to_have_css('color','rgb(223, 139, 22)')
            chart=page.locator('.st-key-dashboard_finance_chart')
            chart.evaluate("node=>node.dataset.mountCheck='retained'")
            start=time.perf_counter();table.evaluate('node=>node.scrollTop=3500')
            expect(table.locator('tr[data-project-id="101"]')).to_be_visible()
            assert table.evaluate('node=>node.scrollTop')==3500
            expect(chart).to_have_attribute('data-mount-check','retained')
            paging=time.perf_counter()-start
            summary=page.get_by_text('1000 matching projects',exact=True)
            summary.click()
            expect(table).not_to_be_visible()
            expect(summary).to_be_visible()
            summary.click()
            expect(page.get_by_text('Shell runs: 1',exact=True)).to_be_visible()
            page.locator('.st-key-dashboard_issue_count button:visible').click()
            dialog=page.get_by_role('dialog')
            expect(dialog.get_by_text('Delivery blocked',exact=True)).to_be_visible()
            expect(dialog.get_by_text('First line\nSecond line',exact=True)).to_be_visible()
            assert dialog.locator('input,textarea').count()==0
            assert dialog.get_by_role('button',name='Edit',exact=True).count()==0
            page.keyboard.press('Escape')
            expect(dialog).not_to_be_visible()
            page.get_by_role('button',name='Advanced filters').click()
            field=page.get_by_role('combobox',name='Filter fields',exact=True)
            field.fill('Project')
            page.get_by_role('option',name='Project',exact=True).click()
            project=page.get_by_role('combobox',name='Project',exact=True)
            project.fill('Project 0001')
            start=time.perf_counter();page.get_by_role('option',name='Project 0001',exact=True).click()
            expect(page.get_by_text('1 matching projects',exact=True)).to_be_visible()
            filtering=time.perf_counter()-start
            expect(page.locator('.st-key-dashboard_advanced_filter [data-testid="stPopoverButton"]')).to_have_css('background-color', 'rgb(196, 16, 57)')
            page.keyboard.press('Escape')
            page.get_by_role('button', name='Advanced filters').click()
            expect(field).not_to_be_visible()
            expect(page.get_by_text('Shell runs: 1',exact=True)).to_be_visible()
            point = page.locator('.st-key-dashboard_finance_chart').first.locator('circle').first
            point.hover()
            expect(page.locator('.st-key-dashboard_finance_chart .tip')).to_contain_text('0.05 kEUR')
            page.get_by_role('heading', name='Finance overview', exact=True).hover()
            expect(page.get_by_role('heading', name='Dashboard', exact=True)).to_have_count(0)
            expect(page.locator('.resource-chart [data-today="2026-06-01"]')).to_have_count(3)
            expect(page.locator('.resource-chart .legend')).to_have_count(1)
            expect(page.locator('.resource-chart .legend')).to_contain_text('Proposed')
            resource = page.locator('.st-key-dashboard_resource_chart_overallocation .resource-chart')
            allocation = page.locator('.st-key-dashboard_resource_chart_allocation .resource-chart')
            expect(allocation.locator('[data-axis-title=allocation]')).to_contain_text('Allocation')
            expect(allocation.locator('[data-pool-id="1"]').first).to_be_visible()
            expect(resource.locator('[data-axis-title="overallocation"]')).to_have_attribute('y', '15')
            assert resource.locator('[data-axis-title="overallocation"]').get_attribute('transform') is None
            expect(resource.locator('[data-axis-title="capacity"]')).to_have_count(0)
            assert resource.locator('[data-quarter]').count() > 0
            assert resource.locator('[data-pool-id]').count() == resource.locator('[data-quarter]').count()
            assert all(re.fullmatch(r'\d+', text) for text in resource.locator('[data-axis]').all_text_contents())
            for axis in ('overallocation','capacity'):
                ticks=resource.locator(f'[data-axis="{axis}"]').all_text_contents()
                assert len(ticks)==len(set(ticks))
            resource.locator('[data-quarter="2026-Q1"]').first.hover()
            expect(resource.get_by_role('tooltip')).to_contain_text('Portfolio simultaneous peak: 3.0')
            expect(resource.get_by_role('tooltip')).not_to_contain_text('Total pools capacity')
            expect(resource.get_by_role('tooltip')).not_to_contain_text('Peak day')
            expect(allocation.locator('[data-hover-line]')).to_have_attribute('visibility','visible')
            allocation.locator('[data-quarter="2026-Q1"]').first.hover()
            expect(allocation.get_by_role('tooltip')).not_to_contain_text('Total capacity')
            expect(allocation.get_by_role('tooltip')).to_contain_text('Portfolio simultaneous peak: 5.0')
            expect(allocation.locator('path')).to_have_count(0)
            expect(resource.locator('[data-hover-line]')).to_have_attribute('visibility','visible')
            expect(resource.locator('.legend')).to_have_count(0)
            expect(allocation.locator('.legend')).to_have_count(0)
            finance_legend=page.locator('.st-key-dashboard_finance_chart .legend').bounding_box()
            finance_plot=page.locator('.st-key-dashboard_finance_chart svg').bounding_box()
            assert finance_legend['y'] >= finance_plot['y']+finance_plot['height']
            expect(page.locator('.st-key-dashboard_issue_card')).to_contain_text('Active Issue')
            issue_icon=page.locator('.st-key-dashboard_issue_count [data-testid=stIconMaterial]').first
            assert issue_icon.evaluate('node=>parseFloat(getComputedStyle(node).fontSize)')>=48
            expect(issue_icon).to_have_css('color','rgb(223, 139, 22)')
            icon_box=issue_icon.bounding_box()
            card_box=page.locator('.st-key-dashboard_issue_card').bounding_box()
            assert abs(icon_box['x']+icon_box['width']/2-card_box['x']-card_box['width']/2)<3
            expect(page.get_by_text('1 matching projects',exact=True)).to_be_visible()
            expect(table.locator('tr[data-project-id="2"]')).to_have_count(0)
            expect(table.locator('tr[data-project-id="1"]')).to_be_visible()
            page.get_by_role('heading',name='Finance overview',exact=True).hover()
            page.screenshot(path=str(tmp_path/'dashboard.png'),full_page=True,animations='disabled')
            (tmp_path/'dashboard-timing.json').write_text(json.dumps({'initial_seconds':initial,'paging_seconds':paging,'filter_seconds':filtering,'shell_runs':1}),encoding='utf-8')
            for chart in (resource, allocation):
                chart.locator('[data-quarter="2026-Q1"][data-pool-id="1"]').click(button='right')
                page.get_by_role('menuitem', name='Filter on this pool', exact=True).click()
                expect(page.get_by_text('Resource pool: Pool A', exact=True)).to_be_visible()
                expect(page.locator('.st-key-dashboard_filter_pool')).to_contain_text('Pool A')
                expect(page.locator('.st-key-dashboard_filter_pool [data-testid="stPopoverButton"]')).to_have_css('background-color', 'rgb(196, 16, 57)')
                page.locator('.st-key-dashboard_filter_pool').get_by_role('button').click()
                expect(page.get_by_role('checkbox', name='Pool A', exact=True)).to_be_checked()
                expect(page.get_by_role('checkbox', name='Pool B', exact=True)).not_to_be_checked()
                page.get_by_test_id('stPopoverBody').get_by_text('Pool B', exact=True).click()
                expect(page.get_by_role('checkbox', name='Pool B', exact=True)).to_be_checked()
                expect(allocation.locator('[data-pool-id="2"]').first).to_be_visible()
                page.get_by_test_id('stPopoverBody').get_by_text('Pool B', exact=True).click()
                expect(page.get_by_role('checkbox', name='Pool B', exact=True)).not_to_be_checked()
                page.keyboard.press('Escape')
                for filtered in (resource, allocation):
                    expect(filtered.locator('[data-pool-id="2"]')).to_have_count(0)
                    expect(filtered.locator('[data-pool-id="1"]').first).to_be_visible()
                allocation.locator('[data-quarter="2026-Q1"]').first.hover()
                expect(allocation.get_by_role('tooltip')).to_contain_text('Minimum capacity in period: 1.0')
                expect(allocation.get_by_role('tooltip')).to_contain_text('Portfolio simultaneous peak: 3.0')
                expect(allocation.locator('path')).to_have_count(1)
                page.get_by_role('button', name='Show all pools', exact=True).click()
                expect(page.locator('.st-key-dashboard_filter_pool')).to_contain_text('All')
                expect(page.locator('.st-key-dashboard_filter_pool [data-testid="stPopoverButton"]')).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
                expect(allocation.locator('[data-pool-id="2"]').first).to_be_visible()
                expect(page.get_by_text('1 matching projects', exact=True)).to_be_visible()
                expect(page.get_by_text('Shell runs: 1', exact=True)).to_be_visible()
            quarter=resource.locator('[data-quarter="2026-Q1"][data-pool-id="1"]')
            quarter.click(button='right')
            page.get_by_role('menuitem', name='Planning & milestones: consuming projects').click()
            expect(page.get_by_text('Planning projects: [1, 2]', exact=True)).to_be_visible()
            assert not browser_errors
        finally:
            browser.close()
