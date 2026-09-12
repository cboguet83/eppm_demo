"""Browser checks for hierarchy catalog editing and optional pool classification."""

import pytest

from tests.test_dialog_browser import popup_server as popup_server, expect, sync_playwright


_APP = '''
from pathlib import Path
import streamlit as st
from app.infrastructure.database.schema_init import init_db
from app.operator_services import create_organization_service, create_resource_pool_service
from app.domain.resources.models import ResourcePool
from app.presentation.pages.hierarchy import render_hierarchy_types
from app.presentation.components.resource_pool_dialogs import _open_edit_pool_dialog
from app.presentation.i18n import set_current_locale

st.set_page_config(layout='wide')
database = str(Path(__file__).with_suffix('.db'))
if not Path(database).exists():
    init_db(database)
    create_resource_pool_service(database).create_pool(ResourcePool('Browser pool'))
set_current_locale('en')
organization = create_organization_service(database)
resources = create_resource_pool_service(database)
render_hierarchy_types(organization)
if st.button('Edit browser pool'):
    _open_edit_pool_dialog(resources, 1)
pool = resources.get_pool_by_id(1)
st.text('Stored hierarchy: ' + str(pool.hierarchy_type_id))
st.text('Saved label: ' + organization.get_all_hierarchy_types()[-1].label('en'))
'''


@pytest.mark.parametrize("popup_server", [_APP], indirect=True)
def test_browser_edits_catalog_and_assigns_then_clears_pool_type(popup_server, tmp_path):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1450, "height": 1100})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(popup_server)
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
