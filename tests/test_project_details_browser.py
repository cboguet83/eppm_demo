"""Project selection reveals complete details despite deliberately slow reads."""

import pytest

from tests.test_dialog_browser import popup_server as popup_server, expect, sync_playwright
from tests.test_portfolio_layout_browser import _APP


_SAMPLE = '''
window.detailFrames=[];
function sample() {
    for(const panel of document.querySelectorAll('.stVerticalBlock[class*="st-key-project_details_panel_"]')) {
        if(getComputedStyle(panel).visibility !== 'hidden' && panel.getBoundingClientRect().height) {
            window.detailFrames.push({
                complete: Boolean(panel.querySelector('dl') && panel.querySelector('[data-testid="stTabs"]') && panel.querySelector('[role="tabpanel"] [data-testid="stHtml"]')),
            });
        }
    }
    requestAnimationFrame(sample);
}
requestAnimationFrame(sample);
'''

_SLOW_APP = _APP.replace('render_application(create_application_workspace(database))', '''
from unittest.mock import patch
from app.application.services.portfolio import PortfolioService
import time
read_catalog=PortfolioService.get_catalog
def slow_catalog(owner, **kwargs):
    time.sleep(.25)
    return read_catalog(owner, **kwargs)
with patch.object(PortfolioService, 'get_catalog', slow_catalog):
    render_application(create_application_workspace(database))
''')


@pytest.mark.parametrize('popup_server', [_SLOW_APP], indirect=True, ids=['details'])
def test_every_visible_selection_frame_contains_the_complete_summary_and_first_section(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width':1500,'height':1100})
            page.add_init_script(_SAMPLE)
            page.goto(popup_server)
            table = page.locator('.st-key-portfolio_master_table')
            expect(table.locator('tbody tr').first).to_be_visible(timeout=30000)
            for index in [0, 1, 0]:
                page.evaluate('window.detailFrames=[]')
                row = table.locator('tbody tr[data-project-id]').nth(index)
                project_id = row.get_attribute('data-project-id')
                row.click()
                panel = page.locator('.st-key-project_details_panel_' + project_id)
                expect(panel).to_have_attribute('data-eppm-details-ready','true')
                expect(panel.get_by_role('tablist')).to_be_visible()
                page.wait_for_function('window.detailFrames.length > 0')
                frames = page.evaluate('window.detailFrames')
                assert frames and all(frame['complete'] for frame in frames), frames
        finally:
            browser.close()
