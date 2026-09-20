"""Browser interaction with the native strategic-priority dashboard filter."""

import psycopg
import pytest
from tests.test_dialog_browser import expect, sync_playwright
from tests.postgresql.dashboard_browser import popup_server


@pytest.mark.parametrize('popup_server', ['dashboard'], indirect=True)
def test_priority_filter_is_between_status_and_pools_and_resets_to_all(popup_server, authorized, tmp_path):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project SET strategic_priority_id=CASE WHEN id<=500 THEN 1 ELSE 4 END')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = popup_server.new_page(browser, viewport={'width':1500,'height':1200})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(popup_server.origin)
            expect(page.get_by_text('1000 matching projects', exact=True)).to_be_visible(timeout=30000)
            buttons = [page.locator(f'.st-key-dashboard_filter_{key} [data-testid="stPopoverButton"]')
                       for key in ('status', 'strategic_priority', 'pool')]
            boxes = [button.bounding_box() for button in buttons]
            assert boxes[0]['x'] < boxes[1]['x'] < boxes[2]['x']
            assert max(box['y'] for box in boxes) - min(box['y'] for box in boxes) < 5
            expect(buttons[1]).to_contain_text('All')
            buttons[1].click()
            page.get_by_text('Strategic', exact=True).click()
            expect(page.get_by_text('500 matching projects', exact=True)).to_be_visible(timeout=30000)
            page.keyboard.press('Escape')
            page.locator('.st-key-dashboard_clear button').click()
            expect(page.get_by_text('1000 matching projects', exact=True)).to_be_visible(timeout=30000)
            expect(buttons[1]).to_contain_text('All')
            expect(buttons[0]).to_contain_text('In Progress')
            page.screenshot(path=str(tmp_path / 'priority-dashboard.png'), full_page=True)
            assert not errors
        finally:
            browser.close()
