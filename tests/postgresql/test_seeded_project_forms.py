"""Actual browser title saves remain valid across the native seeded templates."""

import psycopg

from app.application.ports.maintenance import SeedRequest
from app.infrastructure.postgresql.bulk_seed import generate_projects
from app.infrastructure.postgresql.pool import OperatorDatabase
from tests.performance.browser_load import SAVE_DIAGNOSTIC
from tests.postgresql.browser import native_server
from tests.postgresql.shell_browser import _APP
from tests.test_dialog_browser import expect, sync_playwright


def test_project_editor_can_save_titles_across_seeded_project_templates(authorized, tmp_path):
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
    assert len(project_ids) == 10
    with native_server(authorized, tmp_path, _APP, user_id=1) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={"width": 1500, "height": 1100})
            page.goto(server.origin + "/?nav=portfolio")
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
            expect(page.get_by_test_id("stException")).to_have_count(0)
        finally:
            browser.close()
