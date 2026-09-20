"""Employee import preview, success, default keep policy and fresh uploader."""

import psycopg

from tests.postgresql.browser import native_server
from tests.postgresql.csv_dialog_checks import check_fresh_import_dialog
from tests.postgresql.test_pool_hierarchy_browser import SCREEN
from tests.test_dialog_browser import expect, sync_playwright


APP = SCREEN[:SCREEN.index('render_resource_pools(create_resource_pool_service')] + '''
from app.presentation.pages.organization import render_employees
render_employees(create_organization_service(runtime, access=access))
'''


def test_employee_csv_dialog_import_and_reset(authorized, tmp_path):
    with native_server(authorized, tmp_path, APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = server.new_page(browser, viewport={'width': 1500, 'height': 1100})
            page.goto(server.origin)
            page.get_by_role('button', name='Import CSV').click(timeout=30000)
            dialog = page.get_by_role('dialog')
            expect(dialog.get_by_role('checkbox')).not_to_be_checked()
            dialog.locator('input[type="file"]').set_input_files({
                'name': 'employees.csv', 'mimeType': 'text/csv',
                'buffer': b'firstname,lastname,email,occupation_percentage\nAda,Imported,ada@example.test,80\n'})
            dialog.get_by_role('button', name='Import employees', exact=True).click()
            expect(page.get_by_text('Import successful: 1 employees created, 0 updated, 0 marked deleted.', exact=True)).to_be_visible()
            check_fresh_import_dialog(page, 'employees.csv', 'Import employees',
                b'firstname,lastname,email\nNot,Submitted,pending@example.test\n')
            expect(page.get_by_test_id('stException')).to_have_count(0)
            page.screenshot(path='.local/employee-csv-import.png', full_page=True)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT firstname,occupation_percentage FROM eppm.employee').fetchall() == [('Ada', 80)]
        finally:
            browser.close()
