"""Browser checks for hierarchy catalog editing and optional pool classification."""

import psycopg
import pytest

from app.domain.resources.models import ResourcePool
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.main import create_resource_pool_service
from app.runtime import RuntimeResources
from tests.postgresql.browser import native_server

_playwright = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = _playwright.expect, _playwright.sync_playwright


_APP = '''
import streamlit as st
from app.application.services.business_access import BusinessAccess
from app.main import create_organization_service, create_resource_pool_service
from app.presentation.pages.hierarchy import render_hierarchy_types
from app.presentation.components.resource_pool_dialogs import _open_edit_pool_dialog
from app.presentation.i18n import set_current_locale
from app.runtime import process_runtime
from tests.postgresql.browser import browser_access

st.set_page_config(layout='wide')
runtime = process_runtime()
authentication = browser_access(runtime)
actor = authentication.actor(st.context.cookies.get('eppm_session', ''))
access = BusinessAccess(actor, authentication.policy)
set_current_locale('en')
organization = create_organization_service(runtime, access=access)
resources = create_resource_pool_service(runtime, access=access)
render_hierarchy_types(organization)
pool_id = resources.get_all_pools()[0].id
if st.button('Edit browser pool'):
    _open_edit_pool_dialog(resources, pool_id)
pool = resources.get_pool_by_id(pool_id)
st.text('Stored hierarchy: ' + str(pool.hierarchy_type_id))
st.text('Saved label: ' + organization.get_all_hierarchy_types()[-1].label('en'))
'''


@pytest.fixture
def popup_server(authorized, tmp_path):
    """Seed reference choices separately, then use a native business-admin session."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        ensure_reference_catalog(connection)
    service = create_resource_pool_service(RuntimeResources(authorized.database, authorized.key),
                                           access=authorized.binding(4).access)
    service.create_pool(ResourcePool('Browser pool'))
    with native_server(authorized, tmp_path, _APP) as server:
        yield server


def test_browser_edits_catalog_and_assigns_then_clears_pool_type(popup_server, tmp_path):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = popup_server.new_page(browser, viewport={"width": 1450, "height": 1100})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(popup_server.origin)
            page.get_by_role("textbox", name="Code", exact=True).fill("custom", timeout=30000)
            page.get_by_role("textbox", name="English").fill("Custom hierarchy")
            page.get_by_role("button", name="Save hierarchy type", exact=True).click()
            expect(page.get_by_text("Saved label: Custom hierarchy", exact=True)).to_be_visible()
            page.get_by_role("combobox", name="Hierarchy type", exact=True).click()
            page.get_by_role("option", name="Custom hierarchy", exact=True).click()
            expect(page.get_by_role("textbox", name="Code", exact=True)).to_be_disabled()
            page.get_by_role("textbox", name="English").fill("Renamed hierarchy")
            page.get_by_role("button", name="Save hierarchy type", exact=True).click()
            expect(page.get_by_text("Saved label: Renamed hierarchy", exact=True)).to_be_visible()
            page.get_by_role("button", name="Edit browser pool", exact=True).click()
            dialog = page.get_by_role("dialog")
            picker = dialog.get_by_role("combobox", name="Hierarchy type (optional)", exact=True)
            picker.click()
            page.get_by_role("option", name="Renamed hierarchy", exact=True).click()
            page.screenshot(path=str(tmp_path / "hierarchy-pool-dialog.png"), full_page=True)
            dialog.get_by_role("button", name="Save Changes", exact=False).click()
            expect(page.get_by_text("Stored hierarchy: 8", exact=True)).to_be_visible()
            page.get_by_role("button", name="Edit browser pool", exact=True).click()
            picker.click()
            page.get_by_role("option", name="None", exact=True).click()
            dialog.get_by_role("button", name="Save Changes", exact=False).click()
            expect(page.get_by_text("Stored hierarchy: None", exact=True)).to_be_visible()
            page.screenshot(path=str(tmp_path / "hierarchy-settings.png"), full_page=True)
            assert errors == []
        finally:
            browser.close()
