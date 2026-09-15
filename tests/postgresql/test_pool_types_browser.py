"""Browser verification of pool-type table layout, parent filters, and row actions."""

import pytest
import psycopg

from tests.postgresql.browser import native_server

_playwright = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = _playwright.expect, _playwright.sync_playwright

_APP = '''
import streamlit as st
from app.application.services.business_access import BusinessAccess
from app.main import create_settings_workspace
from app.presentation.pages.settings import render_settings_view
from app.presentation.i18n import set_current_locale
from app.presentation.components.dialog import install_dialog_presentation
from app.runtime import process_runtime
from tests.postgresql.browser import browser_access

st.set_page_config(layout='wide')
install_dialog_presentation()
runtime = process_runtime()
authentication = browser_access(runtime)
actor = authentication.actor(st.context.cookies.get('eppm_session', ''))
access = BusinessAccess(actor, authentication.policy)
set_current_locale('en')
render_settings_view(create_settings_workspace(runtime, access=access))
'''


def test_pool_types_tab_table_parent_filter_and_contextual_crud(authorized, tmp_path):
    """Create and edit a subtype through the same table interaction as Function Types."""
    with native_server(authorized, tmp_path, _APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1450, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(server.origin)
            tab = page.get_by_role('tab', name='Pool Types', exact=True)
            expect(tab).to_be_visible(timeout=30000)
            labels = page.get_by_role('tab').all_text_contents()
            assert labels.index('Pool Types') == labels.index('Employees') + 1
            tab.click()
            table = page.frame_locator('iframe').first
            expect(table.get_by_role('cell', name='Human', exact=True)).to_be_visible()
            expect(table.get_by_role('cell', name='Car', exact=True)).to_be_visible()
            expect(table.locator('#th-parent')).to_be_visible()
            table.locator('.table-toolbar').click(button='right')
            table.locator('#ctx-add-label').click()
            dialog = page.get_by_role('dialog')
            dialog.get_by_role('textbox', name='Name', exact=True).fill('Van')
            dialog.get_by_role('combobox', name='Parent pool type', exact=True).click()
            page.get_by_role('option', name='Car', exact=True).click()
            dialog.get_by_role('button', name='Save pool type', exact=True).click()
            expect(dialog).to_have_count(0)
            row = table.locator('tbody tr').filter(has_text='Van')
            expect(row.get_by_role('cell', name='Car', exact=True)).to_be_visible()
            table.locator('#flt-parent').fill('Car')
            expect(table.locator('tbody tr[data-id]')).to_have_count(1)
            table.locator('#btn-clear').click()
            expect(table.locator('tbody tr[data-id]')).to_have_count(3)
            row.click(button='right')
            table.locator('#ctx-edit-label').click()
            dialog.get_by_role('textbox', name='Name', exact=True).fill('Minibus')
            dialog.get_by_role('button', name='Save pool type', exact=True).click()
            expect(dialog).to_have_count(0)
            renamed = table.get_by_role('cell', name='Minibus', exact=True)
            expect(renamed).to_be_visible()
            page.screenshot(path=str(tmp_path / 'pool-types-table.png'), full_page=True)
            renamed.click(button='right')
            table.locator('#ctx-delete-label').click()
            dialog.get_by_role('button', name='Delete pool type', exact=True).click()
            expect(dialog).to_have_count(0)
            expect(renamed).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT name,parent_pool_type_id FROM eppm.pool_type ORDER BY id').fetchall() == [('Human', None), ('Car', None)]
            assert not errors
        finally:
            browser.close()
