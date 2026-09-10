"""Master-page spacing and filter styling with real browser layout and CSS."""

import pytest

from tests.test_dialog_browser import popup_server as popup_server, expect, sync_playwright


_APP = '''
from pathlib import Path
from app.operator_services import create_maintenance_service, create_application_workspace
from app.presentation.shell import render_application

database = str(Path(__file__).with_suffix('.db'))
if not Path(database).exists():
    create_maintenance_service(database).startup(force=True, projects=2)
render_application(create_application_workspace(database))
'''


@pytest.mark.parametrize("popup_server", [_APP], indirect=True, ids=["portfolio"])
def test_master_layout_has_no_top_gap_or_template_caption_and_colors_only_applied_filters(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            page.goto(popup_server)
            table = page.locator('.st-key-portfolio_master_table')
            expect(table.locator('tbody tr').first).to_be_visible(timeout=30000)
            search = page.get_by_role('textbox', name='Search by Project Name or Code')
            assert page.get_by_test_id('stTextInput').first.bounding_box()['y'] <= 4
            # The native header must not obscure the field after removing padding.
            search.click()
            expect(search).to_be_focused()
            table.locator('tbody tr').first.click()
            heading = page.get_by_role('heading', name='Project Details:', exact=False)
            expect(heading).to_be_visible()
            status = table.get_by_text('matching projects', exact=False)
            panel = page.locator('.stVerticalBlock[class*="st-key-project_details_panel_"]').first
            # Allow native heading spacing, but no intervening caption or divider row.
            status_box = status.bounding_box()
            assert 0 <= panel.bounding_box()['y'] - status_box['y'] - status_box['height'] <= 48
            assert heading.bounding_box()['y'] - panel.bounding_box()['y'] <= 30
            assert not page.get_by_test_id('stCaptionContainer').filter(has_text='Project template:').count()

            button = table.locator('.filter-button').first
            expect(button).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
            button.hover()
            assert button.evaluate("node => getComputedStyle(node).color") != 'rgb(196, 16, 57)'
            button.click()
            menu = table.locator('.filter-menu')
            expect(menu.get_by_role('checkbox').first).to_be_visible()
            menu.get_by_role('checkbox').first.uncheck()
            menu.get_by_role('button', name='Apply', exact=True).click()
            expect(button).to_have_class('filter-button active')
            expect(button).to_have_css('background-color', 'rgb(196, 16, 57)')
            button.click()
            menu.get_by_role('button', name='Select all', exact=True).click()
            menu.get_by_role('button', name='Apply', exact=True).click()
            expect(button).to_have_class('filter-button')
            page.mouse.move(0, 0)
            expect(button).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
        finally:
            browser.close()
