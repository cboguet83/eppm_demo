"""Actual browser title saves remain valid across the native seeded templates."""

import psycopg

from app.application.ports.maintenance import SeedRequest
from app.infrastructure.postgresql.bulk_seed import generate_projects
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.infrastructure.postgresql.property_store import read_values
from tests.performance.browser_load import SAVE_DIAGNOSTIC
from tests.postgresql.browser import native_server
from tests.postgresql.shell_browser import _APP
from tests.test_dialog_browser import expect, sync_playwright


def test_project_editor_title_saves_preserve_properties_across_seeded_templates(authorized, tmp_path):
    property_versions_query = (
        "SELECT tableoid::regclass::text,project_id,param_id,ctid::text,xmin::text "
        "FROM eppm.project_property_value UNION ALL "
        "SELECT tableoid::regclass::text,project_id,param_id,ctid::text,xmin::text "
        "FROM eppm.project_property_value_item ORDER BY 1,2,3,4"
    )
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("DELETE FROM eppm.app_role_assignment WHERE user_id=1")
    OperatorDatabase(authorized.setup.operator_url).run(
        lambda connection: generate_projects(connection, SeedRequest(
            projects=10, min_tasks=0, max_tasks=15, clean_first=True, random_seed=42), year=2026),
        write=True,
    )
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by) "
                           "VALUES(1,'project_editor',%s::jsonb,900,'test setup')", ('{"kind":"all"}',))
        project_ids = [row[0] for row in connection.execute("SELECT id FROM eppm.project ORDER BY id")]
        original_properties = read_values(connection)
        original_versions = connection.execute(property_versions_query).fetchall()
    assert len(project_ids) == 10
    with native_server(authorized, tmp_path, _APP, user_id=1) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={"width": 1500, "height": 1100})
            page.goto(server.origin + "/?nav=portfolio")
            page.locator('.st-key-dashboard_filter_status [data-testid="stPopoverButton"]').click()
            page.locator('.st-key-dashboard_filter_status_clear button').click()
            expect(page.locator('.st-key-portfolio_master_table tr[data-project-id]')).to_have_count(10)
            page.keyboard.press('Escape')
            for project_id in project_ids:
                page.locator(f'.st-key-portfolio_master_table tr[data-project-id="{project_id}"]').click()
                details = page.locator(f".st-key-project_details_panel_{project_id}")
                expect(details).to_have_attribute("data-eppm-details-ready", "true")
                page.get_by_role("button", name="Edit details", exact=True).click()
                dialog = page.get_by_role("dialog")
                name = f"Edited seed project {project_id}"
                dialog.get_by_label("Project Title *", exact=True).fill(name)
                dialog.get_by_role("button", name="Update Project", exact=False).click()
                page.wait_for_function(
                    "values => {const state=(" + SAVE_DIAGNOSTIC + ")(values); "
                    "return state.dialogCount===0 || state.alertCount>0;}",
                    arg={"project": project_id, "name": name},
                )
                assert dialog.get_by_role("alert").count() == 0, dialog.get_by_role("alert").all_text_contents()
                expect(dialog).not_to_be_visible()
                expect(details).to_contain_text(name)
                with psycopg.connect(authorized.setup.operator_url) as connection:
                    assert read_values(connection, owner_id=project_id)[project_id] == original_properties[project_id]
            expect(page.get_by_test_id("stException")).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute(property_versions_query).fetchall() == original_versions
        finally:
            browser.close()
