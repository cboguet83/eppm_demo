"""Browser regression for inline Settings navigation and hierarchy row actions."""

import pytest

from tests.test_dialog_browser import popup_server, sync_playwright, expect
from tests.browser_reruns import completed_rerun

_APP = '''
from dataclasses import replace
from types import SimpleNamespace
import streamlit as st
from app.domain.hierarchy import HierarchyType, normalize_hierarchy_type
from app.presentation.components.application_workspace import ApplicationWorkspace
from app.presentation.navigation import PAGE_PORTFOLIO, PAGE_SETTINGS, PAGE_ACCESS
from app.presentation.shell import render_application
from app.presentation.pages.settings import render_settings_view
from app.presentation.i18n import set_current_locale
st.set_page_config(layout="wide")
set_current_locale("en")
if "records" not in st.session_state:
    st.session_state.records = {1: HierarchyType("division", {"en": "Division"}, 1)}
class Catalog:
    def get_all_function_types(self): return []
    def get_all_hierarchy_types(self): return list(st.session_state.records.values())
    def save_hierarchy_type(self, value):
        value = normalize_hierarchy_type(value)
        identifier = value.id or max(st.session_state.records, default=0) + 1
        st.session_state.records[identifier] = replace(value, id=identifier)
    def delete_hierarchy_type(self, identifier):
        return st.session_state.records.pop(identifier, None) is not None
workspace = SimpleNamespace(organization=Catalog())
render_application(ApplicationWorkspace("settings-browser", {
    PAGE_PORTFOLIO: lambda: st.write("Portfolio"),
    PAGE_SETTINGS: lambda: render_settings_view(workspace),
    PAGE_ACCESS: lambda: st.write("Access"),
}, None))
'''


@pytest.mark.parametrize("popup_server", [_APP], indirect=True, ids=["settings"])
def test_inline_navigation_and_hierarchy_table_crud(popup_server, tmp_path):
    """Use real navigation, table events, and modal widgets in a browser."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1450, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(popup_server)
            nav = page.locator(".st-key-app_sidebar_nav")
            expect(nav.get_by_text("Organization Structure", exact=True)).to_have_count(0)
            with completed_rerun(page):
                nav.get_by_text("Settings", exact=True).click()
            organization = nav.get_by_text("Organization Structure", exact=True)
            expect(organization).to_be_visible()
            expect(nav.get_by_role("radio", name="Organization Structure")).to_be_checked()
            expect(page.locator('[data-testid="stSidebar"] [role="radiogroup"]')).to_have_count(1)
            labels = nav.locator('[role="radiogroup"] label').all_text_contents()
            assert [label.strip() for label in labels] == [
                "Portfolio Overview", "Settings", "Organization Structure",
                "Parameter Definition", "Project configuration", "Tag Management", "Application access",
            ]
            rows = nav.locator('[role="radiogroup"] > label')
            expect(rows.nth(1).locator(':scope > div > div > div').first).to_be_hidden()
            assert rows.nth(2).bounding_box()["x"] > rows.nth(1).bounding_box()["x"] + 15
            expect(page.get_by_role("heading", name="Settings", exact=True)).to_have_count(0)
            page.get_by_role("tab", name="Hierarchy types", exact=True).click()
            table = page.frame_locator("iframe").first
            expect(table.get_by_role("cell", name="Division", exact=True)).to_be_visible()
            table.locator(".table-toolbar").click(button="right")
            expect(table.locator("#ctx-add-label")).to_have_text("Add New Hierarchy type")
            table.locator("#ctx-add-label").click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_role("textbox", name="Code", exact=True).fill("custom")
            dialog.get_by_role("textbox", name="English").fill("Custom hierarchy")
            dialog.get_by_role("textbox", name="Français").fill("Personnalisé")
            dialog.get_by_role("button", name="Save hierarchy type", exact=True).click()
            expect(dialog).to_have_count(0)
            row = table.get_by_role("cell", name="Custom hierarchy", exact=True)
            expect(row).to_be_visible()
            row.click(button="right")
            table.locator("#ctx-edit-label").click()
            expect(dialog.get_by_role("textbox", name="Code", exact=True)).to_be_disabled()
            expect(dialog.get_by_role("textbox", name="Français")).to_have_value("Personnalisé")
            dialog.get_by_role("textbox", name="English").fill("Renamed hierarchy")
            dialog.get_by_role("button", name="Save hierarchy type", exact=True).click()
            expect(dialog).to_have_count(0)
            table.locator("#search-box").fill("Renamed")
            expect(table.locator("tbody tr[data-id]")).to_have_count(1)
            page.screenshot(path=str(tmp_path / "settings-hierarchy-table.png"), full_page=True)
            table.get_by_role("cell", name="Renamed hierarchy", exact=True).click(button="right")
            table.locator("#ctx-delete-label").click()
            delete = dialog.get_by_role("button", name="Delete hierarchy type", exact=True)
            expect(delete).to_be_disabled()
            dialog.get_by_text("Confirm deletion of this unused hierarchy type", exact=True).click()
            delete.click()
            expect(dialog).to_have_count(0)
            expect(table.get_by_role("cell", name="Renamed hierarchy", exact=True)).to_have_count(0)
            assert not errors
        finally:
            browser.close()
