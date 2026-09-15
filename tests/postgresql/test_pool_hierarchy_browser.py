"""Browser coverage for creating a child and inspecting a container pool."""

import psycopg
import pytest
import re

from app.domain.resources.models import ResourcePool
from tests.postgresql.browser import native_server
from tests.postgresql.test_resource_pools import service

playwright_api = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = playwright_api.expect, playwright_api.sync_playwright

SCREEN = '''
import streamlit as st
from app.application.services.business_access import BusinessAccess
from app.main import create_resource_pool_service, create_pool_capacity_service, create_organization_service
from app.presentation.pages.resource_pools import render_resource_pools
from app.presentation.i18n import set_current_locale
from app.runtime import process_runtime
from tests.postgresql.browser import browser_access
from app.presentation.components.dialog import install_dialog_presentation
st.set_page_config(layout='wide')
install_dialog_presentation()
runtime = process_runtime()
authentication = browser_access(runtime)
actor = authentication.actor(st.context.cookies.get('eppm_session', ''))
access = BusinessAccess(actor, authentication.policy)
set_current_locale('en')
render_resource_pools(create_resource_pool_service(runtime, access=access),
    create_pool_capacity_service(runtime, access=access),
    create_organization_service(runtime, access=access), 'planning')
'''


def test_create_child_switches_parent_to_container_and_disables_direct_capacity(authorized, tmp_path):
    parent = service(authorized).create_pool(ResourcePool('Engineering', capacity_fte=20))
    with native_server(authorized, tmp_path, SCREEN) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1400, 'height': 1050})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(server.origin)
            page.get_by_role('button', name='Create child pool', exact=True).click(timeout=30000)
            dialog = page.get_by_role('dialog')
            dialog.get_by_role('textbox', name='Resource Pool Name *', exact=True).fill('Backend')
            dialog.get_by_role('spinbutton', name='Defined capacity (FTE)', exact=True).fill('4')
            dialog.get_by_role('button', name='Save', exact=True).click()
            expect(dialog).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                rows = connection.execute('SELECT name,parent_pool_id,capacity_fte FROM eppm.resource_pool ORDER BY id').fetchall()
                assert rows == [('Engineering', None, None), ('Backend', parent, 4)]
            expect(page.get_by_text('Container pool:', exact=False)).to_be_visible()
            expect(page.get_by_role('combobox', name='Select Resource Pool to Inspect & Configure')).to_have_value(re.compile('.*Engineering.*'))
            page.screenshot(path=str(tmp_path / 'container-pool.png'), full_page=True)
            page.get_by_role('button', name='Edit', exact=True).click()
            expect(dialog.get_by_role('spinbutton', name='Defined capacity (FTE)', exact=True)).to_be_disabled()
            expect(dialog.get_by_role('combobox', name='Parent pool', exact=True)).to_be_visible()
            assert not errors
        finally:
            browser.close()
