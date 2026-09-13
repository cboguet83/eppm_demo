"""Master-page spacing and filter styling with real browser layout and CSS."""

import pytest

from tests.test_dialog_browser import expect, sync_playwright
from tests.postgresql.shell_browser import _APP, popup_server


@pytest.mark.parametrize("popup_server", [_APP], indirect=True, ids=["portfolio"])
def test_master_layout_has_no_top_gap_or_template_caption_and_colors_only_applied_filters(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = popup_server.new_page(browser, viewport={"width": 1500, "height": 1100})
            page.goto(popup_server.origin + '/?nav=portfolio')
            table = page.locator('.st-key-portfolio_master_table')
            expect(table.locator('tbody tr').first).to_be_visible(timeout=30000)
            expect(table.locator('.project-menu-button')).to_have_count(0)
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


@pytest.mark.parametrize("popup_server", [_APP], indirect=True, ids=["planning-shortcut"])
def test_project_details_shortcut_opens_planning_filtered_to_the_selected_project(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = popup_server.new_page(browser, viewport={"width": 1500, "height": 1100})
            page.goto(popup_server.origin + '/?nav=portfolio')
            row = page.locator('.st-key-portfolio_master_table tbody tr[data-project-id]').first
            expect(row).to_be_visible(timeout=30000)
            project_id = row.get_attribute('data-project-id')
            row.click()
            edit = page.get_by_role('button', name='Edit details', exact=True)
            planning = page.get_by_role('button', name='Planning & resources details', exact=True)
            expect(planning).to_be_visible()
            assert abs(edit.bounding_box()['y'] - planning.bounding_box()['y']) < 5
            planning.click()
            expect(page.get_by_role('radio', name='2. 📅 Planning & Milestones')).to_be_checked(timeout=30000)
            selected = page.get_by_test_id('stMultiSelect').get_by_role('group', name='Selected values').locator('[data-tag]')
            expect(selected).to_have_count(1)
            expect(selected).to_contain_text(project_id + ' - ')
            assert len(page.context.pages) == 1
        finally:
            browser.close()
