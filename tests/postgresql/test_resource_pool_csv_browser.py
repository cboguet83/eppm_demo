"""Browser workflow for pool CSV exports, previews and successful imports."""

from pathlib import Path

import pytest
import psycopg

from app.application.services.resource_pool_csv import parse_pools
from app.domain.resources.models import ResourcePool
from tests.postgresql.browser import native_server
from tests.postgresql.csv_dialog_checks import check_fresh_import_dialog
from tests.postgresql.test_pool_hierarchy_browser import SCREEN
from tests.postgresql.test_resource_pools import service

playwright_api = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = playwright_api.expect, playwright_api.sync_playwright

SECURED_LAUNCHER = '''
from pathlib import Path
from secrets import token_urlsafe
import streamlit as st
from starlette.middleware import Middleware
from app.application.services.business_access import BusinessAccess
from app.infrastructure.authentication.downloads import DownloadRoutes
from app.infrastructure.authentication.session_middleware import ApplicationSessionMiddleware
from app.main import create_resource_pool_service
from app.runtime import process_runtime
from app.shared.config.authentication import AuthenticationConfig
from tests.postgresql.browser import browser_access

resources = process_runtime()
access = browser_access(resources)
settings = AuthenticationConfig('development', 'http://localhost:8080/realms/eppm',
    'test-client', token_urlsafe(32), 'http://localhost:8501', token_urlsafe(48), local_http=True)
def export(actor, include_deleted, template):
    return create_resource_pool_service(resources, access=BusinessAccess(actor, access.policy)).export_csv(
        include_deleted=include_deleted, template=template)
app = st.App(Path(__file__).with_name('screen.py'), lifespan=resources.lifespan,
    routes=DownloadRoutes(access, lambda actor, project: '', export_pools=export).routes(),
    middleware=[Middleware(ApplicationSessionMiddleware, access=access, config=settings)])
'''


def test_csv_export_respects_deleted_toggle_and_import_updates_the_hierarchy(authorized, tmp_path):
    pools = service(authorized)
    identity = pools.create_pool(ResourcePool('Original', capacity_fte=2))
    deleted = pools.create_pool(ResourcePool('Hidden'))
    pools.delete_pool(deleted)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.team(team_id,team_name) VALUES (1,'Mapped team')")
        connection.execute("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id) VALUES (%s,'team',1)", (identity,))
    with native_server(authorized, tmp_path, SCREEN, launcher=SECURED_LAUNCHER) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1500, 'height': 1000})
            page.goto(server.origin)
            assert page.request.get(server.origin + '/media/native-download.csv').status == 403
            export = page.get_by_role('link', name='Export CSV')
            expect(export).to_be_visible(timeout=30000)
            with page.expect_download() as download:
                export.click()
            assert download.value.suggested_filename == 'resource_pools.csv'
            assert [row.name for row in parse_pools(Path(download.value.path()).read_bytes())] == ['Original']
            page.get_by_text('Show deleted pools', exact=True).click()
            expect(page.get_by_role('treeitem', name='Hidden (Deleted)', exact=True)).to_be_visible()
            with page.expect_download() as download:
                export.click()
            assert {row.name for row in parse_pools(Path(download.value.path()).read_bytes())} == {'Original', 'Hidden'}
            page.get_by_role('button', name='Import CSV').click()
            dialog = page.get_by_role('dialog')
            expect(dialog.get_by_role('checkbox', name='Delete pools missing from the uploaded CSV')).not_to_be_checked()
            with page.expect_download() as template_download:
                dialog.get_by_role('link', name='Download CSV template').click()
            assert template_download.value.suggested_filename == 'resource_pools_template.csv'
            assert Path(template_download.value.path()).read_bytes().startswith(b'\xef\xbb\xbfpool_id,name,')
            dialog.locator('input[type="file"]').set_input_files({
                'name': 'pools.csv', 'mimeType': 'text/csv',
                'buffer': f'pool_id,name,capacity_fte,deleted_flag\n{identity},Updated,4,false\n999999,New pool,3,false\n'.encode(),
            })
            expect(dialog.get_by_text('2 pool records ready to import.')).to_be_visible()
            dialog.get_by_role('button', name='Import pools', exact=True).click()
            expect(page.get_by_text('Import successful: 1 pools created, 1 updated, 0 marked deleted.', exact=True)).to_be_visible()
            check_fresh_import_dialog(page, 'pools.csv', 'Import pools', b'name\nNot submitted\n')
            expect(page.get_by_role('treeitem', name='Updated', exact=True)).to_be_visible()
            expect(page.get_by_role('treeitem', name='New pool', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='Filter Has Mappings', exact=True)).to_be_visible()
            mapping = page.get_by_role('treeitem', name='Updated', exact=True).locator('.pool-meta').nth(5)
            expect(mapping).to_have_text('✓')
            expect(mapping).to_have_css('font-weight', '900')
            page.screenshot(path=str(tmp_path / 'pool-csv-result.png'), full_page=True)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT capacity_fte FROM eppm.resource_pool WHERE id=%s', (identity,)).fetchone()[0] == 4
                assert connection.execute("SELECT id FROM eppm.resource_pool WHERE name='New pool'").fetchone()[0] != 999999
        finally:
            browser.close()
