"""Browser coverage for creating a child and inspecting a container pool."""

import psycopg
import pytest

from app.domain.resources.models import PoolAssignment, ResourcePool
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
            tree = page.get_by_role('tree', name='Resource pools')
            parent_row = tree.get_by_role('treeitem', name='Engineering', exact=True)
            expect(parent_row).to_be_visible(timeout=30000)
            expect(page.get_by_role('heading', name='Resource Pools Management', exact=False)).to_have_count(0)
            parent_row.click(button='right')
            page.get_by_role('menuitem', name='Create child pool', exact=True).click()
            dialog = page.get_by_role('dialog')
            dialog.get_by_role('textbox', name='Resource Pool Name *', exact=True).fill('Backend')
            dialog.get_by_role('spinbutton', name='Defined capacity (FTE)', exact=True).fill('4')
            dialog.get_by_role('button', name='Save', exact=True).click()
            expect(dialog).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                rows = connection.execute('SELECT name,parent_pool_id,capacity_fte FROM eppm.resource_pool ORDER BY id').fetchall()
                assert rows == [('Engineering', None, 0), ('Backend', parent, 4)]
            expect(page.get_by_text('No overassigned periods for Engineering.', exact=True)).to_be_visible()
            expect(parent_row).to_have_attribute('aria-selected', 'true')
            expect(parent_row).to_contain_text('4.00')
            child_row = tree.get_by_role('treeitem', name='Backend', exact=True)
            expect(child_row).to_have_attribute('aria-level', '2')
            parent_row.press('ArrowLeft')
            expect(child_row).to_have_count(0)
            expect(parent_row).to_be_focused()
            page.keyboard.press('ArrowRight')
            expect(child_row).to_be_visible()
            child_row.click()
            expect(child_row).to_have_attribute('aria-selected', 'true')
            expect(page.get_by_text('No overassigned periods for Backend.', exact=True)).to_be_visible()
            parent_row.click()
            expect(parent_row).to_have_attribute('aria-selected', 'true')
            expect(page.get_by_role('button', name='Edit', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='Delete', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='Create child pool', exact=True)).to_have_count(0)
            expect(parent_row).to_have_css('font-weight', '700')
            assert abs(parent_row.bounding_box()['height'] - 36.4) < 1
            expect(tree.get_by_text('Pool type', exact=True)).to_be_visible()
            expect(tree.get_by_text('Hierarchy type', exact=True)).to_be_visible()
            expect(tree.get_by_text('Mapped Capacity (FTE)', exact=True)).to_be_visible()
            expect(parent_row).to_contain_text('Human')
            expect(tree.get_by_text('Pool Capacity (FTE)', exact=True)).to_be_visible()
            expect(tree.get_by_text('Mapped Capacity (FTE)', exact=True)).to_have_attribute('title', 'FTE calculated from the employees mapped in the pool.')
            expect(page.get_by_text('Deduplicated Assigned Capacity Breakdown', exact=True)).to_be_visible()
            expect(page.get_by_text('Active Allocations on Projects & Tasks', exact=True)).to_be_visible()
            expect(parent_row).to_have_css('background-color', 'rgb(241, 243, 245)')
            expect(page.get_by_text('No overassigned periods for Engineering.', exact=True)).to_be_visible()
            page.screenshot(path=str(tmp_path / 'container-pool.png'), full_page=True)
            parent_row.press('Shift+F10')
            page.get_by_role('menuitem', name='Edit pool', exact=True).click()
            expect(dialog.get_by_role('spinbutton', name='Defined capacity (FTE)', exact=True)).to_be_disabled()
            expect(dialog.get_by_role('combobox', name='Parent pool', exact=True)).to_be_visible()
            dialog.get_by_role('textbox', name='Resource Pool Name *', exact=True).fill('Engineering renamed')
            dialog.get_by_role('button', name='Save Changes', exact=True).click()
            expect(dialog).to_have_count(0)
            expect(tree.get_by_role('treeitem', name='Engineering renamed', exact=True)).to_contain_text('4.00')
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT capacity_fte FROM eppm.resource_pool WHERE id=%s', (parent,)).fetchone() == (0,)
            assert not errors
        finally:
            browser.close()


def test_context_child_creation_warns_for_assigned_pool(authorized, tmp_path):
    pools = service(authorized)
    parent = pools.create_pool(ResourcePool('Assigned pool', capacity_fte=8))
    pools.create_assignment(PoolAssignment(parent, 1, 1))
    with native_server(authorized, tmp_path, SCREEN) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser)
            page.goto(server.origin)
            row = page.get_by_role('treeitem', name='Assigned pool', exact=True)
            row.click(button='right', timeout=30000)
            page.get_by_role('menuitem', name='Create child pool', exact=True).click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            expect(page.get_by_text('Remove or reassign them before adding children.', exact=False).first).to_be_visible()
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT id,capacity_fte FROM eppm.resource_pool').fetchall() == [(parent, 8)]
        finally:
            browser.close()
