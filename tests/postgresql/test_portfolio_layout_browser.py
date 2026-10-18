"""Master-page spacing and filter styling with real browser layout and CSS."""

import pytest

from tests.test_dialog_browser import expect, sync_playwright
from tests.postgresql.shell_browser import _APP, popup_server


_SLOW_SAVE_APP = _APP.replace("render_application(workspace)", '''
import time
from app.presentation.pages import portfolio

if not getattr(portfolio._portfolio_selection, "confirmation_test_delay", False):
    original_selection = portfolio._portfolio_selection
    def delayed_selection(*args, _original=original_selection, **kwargs):
        if "portfolio_selection_override" in st.session_state:
            time.sleep(4.5)  # A refresh can outlast the default four-second toast.
        return _original(*args, **kwargs)
    delayed_selection.confirmation_test_delay = True
    portfolio._portfolio_selection = delayed_selection
render_application(workspace)
''')


@pytest.mark.parametrize("popup_server", [_APP, _SLOW_SAVE_APP], indirect=True,
                         ids=["repeated-save-confirmation", "slow-save-refresh"])
def test_each_project_save_shows_a_new_confirmation_after_the_previous_one_is_dismissed(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = popup_server.new_page(browser, viewport={"width": 1500, "height": 1100})
            page.goto(popup_server.origin + "/?nav=portfolio")
            row = page.locator(".st-key-portfolio_master_table tbody tr[data-project-id]").first
            expect(row).to_be_visible(timeout=30000)
            project_id = row.get_attribute("data-project-id")
            row.click()
            details = page.locator(".st-key-project_details_panel_" + project_id)
            expect(details).to_have_attribute("data-eppm-details-ready", "true")
            for index in range(3):
                page.get_by_role("button", name="Edit details", exact=True).click()
                dialog = page.get_by_role("dialog")
                title = f"Confirmed project save {index}"
                dialog.get_by_label("Project Title *", exact=True).fill(title)
                dialog.get_by_role("button", name="Update Project", exact=False).click()
                expect(dialog).not_to_be_visible(timeout=10000)
                expect(details).to_contain_text(title, timeout=10000)
                toast = page.get_by_test_id("stToast").filter(has_text="Project details updated.")
                expect(toast).to_be_visible(timeout=5000)
                toast.get_by_role("button", name="Close", exact=True).click()
                expect(toast).not_to_be_visible()
            expect(page.get_by_test_id("stException")).to_have_count(0)
        finally:
            browser.close()


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
            filters = page.locator('.st-key-organization_service_frame')
            assert filters.bounding_box()['y'] <= 4
            # Shared filters replaced the old standalone search field.
            advanced = page.get_by_role('button', name='Advanced filters', exact=False)
            advanced.click()
            expect(page.get_by_role('combobox', name='Filter fields', exact=True)).to_be_visible()
            page.keyboard.press('Escape')
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
            expect(page.get_by_role('radio', name='Planning & Milestones', exact=True)).to_be_checked(timeout=30000)
            chart = page.frame_locator('iframe[title*="interactive_gantt"]')
            expect(chart.locator('[data-part=project-count]')).to_have_text('1 Project')
            expect(chart.locator('.planning-frozen-row[data-target-kind=projects]')).to_have_count(1)
            expect(chart.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="' + project_id + '"]')).to_be_visible()
            assert len(page.context.pages) == 1
        finally:
            browser.close()
