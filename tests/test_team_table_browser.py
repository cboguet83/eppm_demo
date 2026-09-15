"""Verify the parent-team column and filtering in the existing table component."""

import pytest

from tests.test_dialog_browser import popup_server, sync_playwright, expect


_APP = '''
from app.domain.organization.models import Team
from app.presentation.pages.organization import render_teams
from app.presentation.i18n import set_current_locale
set_current_locale('en')
class Catalog:
    def get_all_functions(self): return []
    def get_all_hierarchy_types(self): return []
    def get_all_teams(self):
        return [Team('Root <one>', team_id=1), Team('Other', team_id=2),
                Team('Child', team_id=3, parent_team_id=1),
                Team('Child B', team_id=4, parent_team_id=2)]
render_teams(Catalog())
'''


@pytest.mark.parametrize('popup_server', [_APP], indirect=True)
def test_parent_column_shows_names_filters_and_clears(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(popup_server)
            table = page.frame_locator('iframe[title*="interactive_team_table"]')
            expect(table.locator('#th-parent')).to_have_text('Parent team')
            expect(table.locator('tr[data-id="3"] td').last).to_have_text('Root <one>')
            table.locator('#flt-parent').fill('root')
            expect(table.locator('#table-body tr')).to_have_count(1)
            expect(table.locator('tr[data-id="3"]')).to_be_visible()
            table.locator('#btn-clear').click()
            expect(table.locator('#table-body tr')).to_have_count(4)
            table.locator('#search-box').fill('root')
            expect(table.locator('#table-body tr')).to_have_count(2)
        finally:
            browser.close()
