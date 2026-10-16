"""Planning starts its service frame at the same height as the dashboard."""

import re

import pytest

from tests.postgresql.shell_browser import _APP, popup_server
from tests.test_dialog_browser import expect, sync_playwright


@pytest.mark.parametrize('popup_server', [_APP], indirect=True)
def test_service_frame_spacing_in_full_shell(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = popup_server.new_page(browser, viewport={'width': 1600, 'height': 1000})
            tops = []
            for view in ('dashboard', 'planning'):
                page.goto(popup_server.origin + '/?nav=' + view)
                frame = page.locator('.st-key-organization_service_frame')
                expect(frame).to_be_visible(timeout=30000)
                expect(frame.get_by_role('button').first).to_be_visible()
                page.wait_for_timeout(500)
                top = frame.bounding_box()['y']
                tops.append(top)
                padding = frame.evaluate('node => getComputedStyle(node).paddingTop')
                assert padding == '2px'
                page.screenshot(path=f'.local/{view}-service-spacing.png')
                if view == 'planning':
                    control = page.locator('.st-key-planning_project_filter_slot button')
                    expect(control).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
                    control.click()
                    choices = page.locator('.st-key-ms_multi_projects')
                    choices.get_by_role('combobox').click()
                    page.get_by_role('option', name=re.compile('Project 0001')).click()
                    chart = page.frame_locator('iframe[title*="interactive_gantt"]')
                    expect(chart.locator('#badge-projects-count-text')).to_have_text('1 Project', timeout=15000)
                    page.keyboard.press('Escape')
                    page.keyboard.press('Escape')
                    expect(control).to_have_css('background-color', 'rgb(196, 16, 57)', timeout=15000)
            assert abs(tops[0] - tops[1]) <= 4, tops
        finally:
            browser.close()
