"""Team hierarchy, CSV transport and shared context menus in a real browser."""

from pathlib import Path

import psycopg
import pytest

from app.application.services.team_csv import parse_teams
from app.domain.organization.models import Team
from tests.postgresql.browser import native_server
from tests.postgresql.test_pool_hierarchy_browser import SCREEN as POOL_SCREEN
from tests.postgresql.test_resource_pool_csv_browser import SECURED_LAUNCHER
from tests.postgresql.test_team_overview import mapped_team, service

playwright_api = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = playwright_api.expect, playwright_api.sync_playwright

SCREEN = POOL_SCREEN[:POOL_SCREEN.index('render_resource_pools(create_resource_pool_service')] + '''
from app.presentation.pages.teams import render_teams
render_teams(create_organization_service(runtime, access=access))
'''
LAUNCHER = SECURED_LAUNCHER.replace('from app.main import create_resource_pool_service',
    'from app.main import create_organization_service').replace('create_resource_pool_service(resources',
    'create_organization_service(resources').replace('include_deleted=include_deleted, template=template)',
    "'teams', include_deleted=include_deleted, template=template)").replace('export_pools=export', 'export_teams=export')


def test_team_hierarchy_csv_selection_context_and_deleted_rows(mapped_team, tmp_path):
    org = service(mapped_team)
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        connection.execute("SELECT setval(pg_get_serial_sequence('eppm.team','team_id'),1)")
    container = org.create_team(Team('Alpha container', parent_team_id=1))
    org.create_team(Team('Nested', parent_team_id=container))
    org.create_team(Team('Zulu leaf', parent_team_id=1))
    deleted = org.create_team(Team('Deleted team'))
    org.delete_team(deleted)
    with native_server(mapped_team, tmp_path, SCREEN, launcher=LAUNCHER) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1600, 'height': 1050})
            page.goto(server.origin)
            tree = page.get_by_role('tree', name='Teams', exact=True)
            expect(tree).to_be_visible(timeout=30000)
            assert tree.get_by_role('treeitem').evaluate_all('(rows)=>rows.map(row=>row.getAttribute("aria-label"))') == [
                'Team 1', 'Zulu leaf', 'Alpha container', 'Nested']
            expect(page.get_by_role('button', name='Filter Manager function', exact=True)).to_be_visible()
            row = tree.get_by_role('treeitem', name='Team 1', exact=True)
            row.click()
            expect(row).to_have_attribute('aria-selected', 'true')
            expect(page.get_by_role('heading', name='Team active allocations')).to_be_visible()
            page.get_by_text('Show deleted teams', exact=True).click()
            expect(tree.get_by_role('treeitem', name='Deleted team (Deleted)', exact=True)).to_be_visible()
            with page.expect_download() as download:
                page.get_by_role('link', name='Export CSV').click()
            assert len(parse_teams(Path(download.value.path()).read_bytes())) == 5
            page.get_by_role('button', name='Import CSV').click()
            modal = page.get_by_role('dialog')
            expect(modal.get_by_role('checkbox', name='Delete teams missing from the uploaded CSV')).not_to_be_checked()
            modal.locator('input[type="file"]').set_input_files({'name': 'teams.csv', 'mimeType': 'text/csv',
                'buffer': b'team_name\nImported team\n'})
            modal.get_by_role('button', name='Import teams', exact=True).click()
            expect(tree.get_by_role('treeitem', name='Imported team', exact=True)).to_be_visible()
            expect(tree.get_by_role('treeitem', name='Team 1', exact=True)).to_be_visible()
            target = tree.get_by_role('treeitem', name='Deleted team (Deleted)', exact=True)
            target.click(button='right')
            expect(page.get_by_role('menuitem', name='Undelete team', exact=True)).to_be_visible()
            page.get_by_role('menuitem', name='Undelete team', exact=True).click()
            expect(tree.get_by_role('treeitem', name='Deleted team', exact=True)).to_be_visible()
            page.screenshot(path=str(tmp_path / 'team-hierarchy.png'), full_page=True)
        finally:
            browser.close()
