"""Function hierarchy menus and authenticated CSV round trips in Chromium."""

from pathlib import Path

import pytest

from app.application.services.function_csv import parse_functions
from app.domain.organization.models import OrgFunction
from tests.postgresql.browser import native_server
from tests.postgresql.csv_dialog_checks import check_fresh_import_dialog
from tests.postgresql.test_organization import organization
from tests.postgresql.test_team_hierarchy_browser import LAUNCHER as TEAM_LAUNCHER, SCREEN as TEAM_SCREEN

playwright_api = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = playwright_api.expect, playwright_api.sync_playwright
SCREEN = TEAM_SCREEN.replace('from app.presentation.pages.teams import render_teams',
    'from app.presentation.pages.organization import render_functions').replace('render_teams(', 'render_functions(')
LAUNCHER = TEAM_LAUNCHER.replace("'teams'", "'functions'").replace('export_teams=export', 'export_functions=export')


def test_function_tree_import_export_and_restore(organization, authorized, tmp_path):
    root = organization.create_function(OrgFunction('Root'))
    organization.create_function(OrgFunction('Child', manager_function_id=root))
    deleted = organization.create_function(OrgFunction('Retired'))
    organization.delete_function(deleted)
    with native_server(authorized, tmp_path, SCREEN, launcher=LAUNCHER) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1600, 'height': 1000})
            page.goto(server.origin)
            tree = page.get_by_role('tree', name='Functions', exact=True)
            expect(tree).to_be_visible(timeout=30000)
            expect(tree.get_by_role('treeitem')).to_have_count(2)
            expect(page.get_by_role('button', name='Filter Primary Manager', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='Filter ID', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='Filter Hierarchy Level', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='Filter Has Reports', exact=True)).to_have_count(0)
            for column in ('Function Title', 'Function Type', 'Dual Manager', 'FTE %'):
                expect(page.get_by_role('button', name=f'Filter {column}', exact=True)).to_be_visible()
            with page.expect_download() as download:
                page.get_by_role('link', name='Export CSV').click()
            assert len(parse_functions(Path(download.value.path()).read_bytes())) == 2
            page.get_by_text('Show deleted functions', exact=True).click()
            row = tree.get_by_role('treeitem', name='Retired (Deleted)', exact=True)
            row.click(button='right')
            page.get_by_role('menuitem', name='Undelete function', exact=True).click()
            expect(tree.get_by_role('treeitem', name='Retired', exact=True)).to_be_visible()
            page.get_by_role('button', name='Import CSV').click()
            modal = page.get_by_role('dialog')
            expect(modal.get_by_role('checkbox', name='Delete functions missing from the uploaded CSV')).not_to_be_checked()
            modal.locator('input[type="file"]').set_input_files({'name': 'invalid.csv', 'mimeType': 'text/csv',
                'buffer': b'name,fte_percentage\nBroken,no\n'})
            expect(modal.get_by_text('Function import failed while reading the CSV. No changes were saved.')).to_be_visible()
            expect(modal.get_by_text('Row 2, function "Broken": fte_percentage must be a whole number between 0 and 100.', exact=True)).to_be_visible()
            expect(modal.get_by_role('button', name='Import functions', exact=True)).to_have_count(0)
            modal.locator('input[type="file"]').set_input_files({'name': 'invalid-parent.csv', 'mimeType': 'text/csv',
                'buffer': b'name,manager_function_id\nBroken,99999\n'})
            modal.get_by_role('button', name='Import functions', exact=True).click()
            expect(modal.get_by_text('Function import failed during validation or database save. No changes were saved.')).to_be_visible()
            expect(modal.get_by_text('manager_function_id=99999', exact=False)).to_be_visible()
            modal.locator('input[type="file"]').set_input_files({'name': 'functions.csv', 'mimeType': 'text/csv',
                'buffer': b'name\nImported function\n'})
            modal.get_by_role('button', name='Import functions', exact=True).click()
            expect(tree.get_by_role('treeitem', name='Imported function', exact=True)).to_be_visible()
            expect(tree.get_by_role('treeitem', name='Broken', exact=True)).to_have_count(0)
            expect(tree.get_by_role('treeitem', name='Root', exact=True)).to_be_visible()
            check_fresh_import_dialog(page, 'functions.csv', 'Import functions', b'name\nNot submitted\n')
            tree.get_by_role('treeitem', name='Root', exact=True).click(button='right')
            page.get_by_role('menuitem', name='Edit function', exact=True).click()
            edit = page.get_by_role('dialog')
            expect(edit).to_be_visible()
            expect(edit.get_by_text('Hierarchy Level', exact=False)).to_have_count(0)
            edit.get_by_role('textbox', name='Function Title *', exact=True).fill('Root renamed')
            edit.get_by_role('button', name='Save Changes', exact=True).click()
            expect(tree.get_by_role('treeitem', name='Root renamed', exact=True)).to_be_visible()
            page.screenshot(path=str(tmp_path / 'function-hierarchy.png'), full_page=True)
        finally:
            browser.close()
