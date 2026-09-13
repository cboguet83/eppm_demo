"""Rendered numeric-property dialogs use exact text with real native storage."""

from decimal import Decimal

import psycopg
import pytest

from tests.postgresql.shell_browser import _APP, popup_server
from tests.performance.browser_load import SAVE_DIAGNOSTIC
from tests.test_dialog_browser import expect, sync_playwright


@pytest.mark.parametrize("popup_server", [_APP], indirect=True, ids=["native-numeric-property"])
def test_numeric_property_dialog_opens_saves_and_retries_without_rounding(popup_server, authorized):
    original = "9007199254740993.1234567890123456789"
    changed = "-0.000000000000000000123456789"
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) "
                           "VALUES('exact_quantity','Numeric quantity','NUMBER')")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,number_value) "
                           "VALUES(1,'exact_quantity','number',%s)", (Decimal(original),))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = popup_server.new_page(browser, viewport={"width": 1500, "height": 1100})
            page.goto(popup_server.origin + "/?nav=portfolio")
            page.locator('.st-key-portfolio_master_table tr[data-project-id="1"]').click()
            details = page.locator(".st-key-project_details_panel_1")
            expect(details).to_have_attribute("data-eppm-details-ready", "true")
            page.get_by_role("button", name="Edit details", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("Project Title *", exact=True).fill("Title-only numeric save")
            dialog.get_by_role("button", name="Update Project", exact=False).click()
            expect(dialog).not_to_be_visible()
            expect(details).to_contain_text("Title-only numeric save")
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute("SELECT number_value FROM eppm.project_property_value "
                                          "WHERE project_id=1 AND param_id='exact_quantity'").fetchone() == (Decimal(original),)

            page.get_by_role("button", name="Edit details", exact=True).click()
            quantity = dialog.get_by_label("Numeric quantity", exact=True)
            expect(quantity).to_have_value(original)
            for tab in dialog.get_by_role("tab").all():
                tab.click()
                if quantity.is_visible():
                    break
            expect(quantity).to_be_visible()
            quantity.fill("not a number")
            dialog.get_by_role("button", name="Update Project", exact=False).click()
            expect(dialog.get_by_role("alert")).to_have_text("Enter a finite numeric property value.")
            expect(quantity).to_have_value("not a number")
            diagnostic = page.evaluate(SAVE_DIAGNOSTIC, {"project": 1, "name": "Title-only numeric save"})
            assert diagnostic["dialogCount"] == 1 and diagnostic["alertCount"] >= 1
            assert diagnostic["exceptionCount"] == 0
            assert diagnostic["editButtons"] == [{"disabled": False, "visible": True}]
            quantity.fill(changed)
            dialog.get_by_role("button", name="Update Project", exact=False).click()
            expect(dialog).not_to_be_visible()
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute("SELECT number_value FROM eppm.project_property_value "
                                          "WHERE project_id=1 AND param_id='exact_quantity'").fetchone() == (Decimal(changed),)
            expect(page.get_by_test_id("stException")).to_have_count(0)
        finally:
            browser.close()
