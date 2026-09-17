"""Verify team hierarchy ancestry and shared Excel-style header filters."""

import pytest

from tests.test_dialog_browser import popup_server, sync_playwright, expect


_APP = '''
from app.domain.organization.models import Team
from app.application.services.team_capacity import TeamCapacity, TeamOverview
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
    def team_overview(self, **kwargs):
        return TeamOverview(self.get_all_teams(), [], {identity: TeamCapacity() for identity in range(1,5)}, [])
render_teams(Catalog())
'''


@pytest.mark.parametrize('popup_server', [_APP], indirect=True)
def test_team_filter_keeps_matching_children_and_their_ancestors(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(popup_server)
            tree = page.get_by_role('tree', name='Teams', exact=True)
            expect(tree.get_by_role('treeitem')).to_have_count(4)
            expect(tree.get_by_role('treeitem', name='Child', exact=True)).to_have_attribute('aria-level', '2')
            tree.get_by_role('button', name='Filter Team', exact=True).click()
            popup = page.get_by_role('dialog', name='Filter Team', exact=True)
            popup.get_by_label('Select all', exact=True).uncheck()
            popup.get_by_label('Child', exact=True).check()
            popup.get_by_role('button', name='Apply', exact=True).click()
            expect(tree.get_by_role('treeitem')).to_have_count(2)
            expect(tree.get_by_role('treeitem', name='Root <one>', exact=True)).to_be_visible()
            expect(tree.get_by_role('treeitem', name='Child', exact=True)).to_be_visible()
        finally:
            browser.close()
