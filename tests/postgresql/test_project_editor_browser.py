"""Scoped editors can save titles while preserving unset protected properties."""

import psycopg

from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog, install_schema_catalog
from tests.postgresql.browser import native_server
from tests.postgresql.shell_browser import _APP
from tests.test_dialog_browser import expect, sync_playwright


def test_scoped_editor_repeated_title_saves_preserve_absent_and_null_enums(authorized, tmp_path):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        ensure_reference_catalog(connection)
        install_schema_catalog(connection)
        connection.execute("UPDATE eppm.project SET status='In Progress',project_type_id=(SELECT id FROM eppm.project_type WHERE is_general) WHERE id=1")
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) "
                           "VALUES('scope_absent','Absent scope','ENUM'),('scope_null','Null scope','ENUM')")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind) VALUES(1,'scope_null','null')")
    with native_server(authorized, tmp_path, _APP, user_id=1) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={"width": 1500, "height": 1100})
            page.goto(server.origin + "/?nav=portfolio")
            page.locator('.st-key-portfolio_master_table tr[data-project-id="1"]').click()
            details = page.locator(".st-key-project_details_panel_1")
            expect(details).to_have_attribute("data-eppm-details-ready", "true")
            for index in range(2):
                page.get_by_role("button", name="Edit details", exact=True).click()
                dialog = page.get_by_role("dialog")
                expect(dialog.get_by_label("Absent scope", exact=True)).to_be_disabled()
                expect(dialog.get_by_label("Null scope", exact=True)).to_be_disabled()
                name = f"Scoped editor title {index}"
                dialog.get_by_label("Project Title *", exact=True).fill(name)
                dialog.get_by_role("button", name="Update Project", exact=False).click()
                expect(dialog).not_to_be_visible()
                expect(details).to_contain_text(name)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute("SELECT param_id,kind FROM eppm.project_property_value "
                                          "WHERE project_id=1 AND param_id IN ('scope_absent','scope_null')").fetchall() == [("scope_null", "null")]
            expect(page.get_by_test_id("stException")).to_have_count(0)
        finally:
            browser.close()
