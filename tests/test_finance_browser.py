"""Real finance grid editing, version dialogs, CSV and clipboard workflows."""

import json
import re
from pathlib import Path

import pytest

from tests.test_dialog_browser import popup_server as popup_server, expect, sync_playwright


_APP = '''
from pathlib import Path
from datetime import date
from contextlib import closing
import streamlit as st
from app.infrastructure.database.schema_init import init_db
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.operator_context import deployment_access
from app.main import create_finance_service
from app.presentation.pages.finance import render_finance
from app.presentation.i18n import set_current_locale

database = str(Path(__file__).with_suffix('.db'))
st.set_page_config(layout='wide')
fresh = not Path(database).exists()
if fresh:
    init_db(database)
    with closing(get_db(database)) as conn, conn:
        conn.execute("INSERT INTO wbs(code,description) VALUES('A.1','Known description')")
service = create_finance_service(database, access=deployment_access())
service.today = lambda: date(2026,6,1)
set_current_locale('en')
st.session_state['shell_runs'] = st.session_state.get('shell_runs',0)+1
st.caption('Shell runs: '+str(st.session_state['shell_runs']))
render_finance(service)
'''


def paste(locator, text):
    """Deliver the same plain-text clipboard event used by Excel paste."""
    locator.evaluate("""(node,text)=>{const clipboard=new DataTransfer();clipboard.setData('text/plain',text);
        node.dispatchEvent(new ClipboardEvent('paste',{clipboardData:clipboard,bubbles:true,cancelable:true}));}""", text)


_NAV_APP = _APP.replace('render_finance(service)\n', '''
page = st.sidebar.radio('Page', ['Finance', 'Dashboard'], key='test_page')
if page == 'Finance':
    render_finance(service)
else:
    st.header('Dashboard destination')
''')


@pytest.mark.parametrize('popup_server', [_NAV_APP], indirect=True, ids=['finance-navigation'])
def test_saving_finance_releases_sidebar_navigation(popup_server):
    """Saving a dirty plan must release its old browser navigation guard."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width':1500, 'height':1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(popup_server)
            grid = page.locator('.finance')
            grid.get_by_role('button', name='Edit', exact=True).click(timeout=30000)
            code = grid.get_by_role('textbox', name='1 WBS code', exact=True)
            expect(code).to_be_visible(timeout=30000)
            code.fill('A.1')
            code.press('Tab')
            grid.get_by_role('textbox', name='1 2026', exact=True).fill('42')
            grid.get_by_role('button', name='Save new version', exact=True).click()
            dialog = grid.get_by_role('dialog')
            dialog.get_by_role('textbox', name='Name', exact=True).fill('Navigation baseline')
            dialog.get_by_role('combobox', name='Status', exact=True).select_option('Draft')
            dialog.get_by_role('button', name='Confirm', exact=True).click()
            expect(grid.locator('.plan-name')).to_have_text('Navigation baseline')
            page.get_by_text('Dashboard', exact=True).click()
            expect(page.get_by_role('heading', name='Dashboard destination')).to_be_visible()
            page.get_by_text('Finance', exact=True).click()
            expect(grid.locator('.plan-name')).to_have_text('Navigation baseline')
            grid.get_by_role('button', name='Edit', exact=True).click()
            amount = grid.get_by_role('textbox', name='1 2026', exact=True)
            amount.fill('55')
            page.get_by_text('Dashboard', exact=True).click()
            dialog = grid.get_by_role('dialog')
            expect(dialog).to_be_visible()
            dialog.get_by_role('button', name='Cancel', exact=True).click()
            expect(amount).to_have_value('55')
            page.get_by_text('Dashboard', exact=True).click()
            dialog.get_by_role('button', name='Discard changes', exact=True).click()
            expect(page.get_by_role('heading', name='Dashboard destination')).to_be_visible()
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize('popup_server', [_APP], indirect=True, ids=['finance-workflow'])
def test_finance_grid_saves_versions_imports_and_cancellations_without_shell_reruns(popup_server,tmp_path):
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={'width':1500,'height':1000})
            page.goto(popup_server)
            grid=page.locator('.finance')
            expect(grid.get_by_role('button',name='Edit',exact=True)).to_be_visible(timeout=30000)
            expect(grid.get_by_role('button',name='Save new version',exact=True)).to_be_disabled()
            expect(grid.get_by_role('button',name='Import CSV',exact=True)).to_be_disabled()
            assert grid.locator('tbody input').count()==0
            paste(grid.locator('.viewport'), 'LOCKED\tignored\t42')
            grid.get_by_role('button',name='Edit',exact=True).click(timeout=30000)
            expect(grid.get_by_role('textbox',name='1 WBS code',exact=True)).to_have_value('')
            expect(grid.get_by_role('button',name='Save new version',exact=True)).to_be_enabled()
            expect(grid.get_by_role('textbox',name='1 WBS code',exact=True)).to_be_visible(timeout=30000)
            assert grid.locator('tbody tr[data-row]').count()==25
            assert grid.locator('tbody tr.unused').count()==25
            assert grid.get_by_role('button',name='Add WBS',exact=True).count()==0
            assert grid.locator('.viewport').evaluate('(node)=>node.scrollLeft')==550
            grid.get_by_role('textbox',name='1 WBS code',exact=True).fill('A.1')
            grid.get_by_role('textbox',name='1 WBS code',exact=True).press('Tab')
            expect(grid.get_by_text('Known description',exact=True)).to_be_visible()
            expect(grid.locator('tr[data-row="0"]')).not_to_have_class('unused')
            expect(grid.get_by_role('textbox',name='1 2026',exact=True)).to_be_focused()
            amount=grid.get_by_role('textbox',name='1 2026',exact=True)
            amount.fill('123.45')
            amount.click()
            paste(amount,'10.25\t20,50')
            expect(amount).to_have_value('10.25')
            expect(grid.get_by_role('textbox',name='1 2027',exact=True)).to_have_value('20,50')
            assert grid.get_by_role('textbox',name='1 2025',exact=True).count()==0
            expect(page.get_by_text('Shell runs: 1',exact=True)).to_be_visible()
            grid.get_by_role('button',name='Save new version',exact=True).click()
            dialog=grid.get_by_role('dialog')
            dialog.get_by_role('textbox',name='Name',exact=True).fill('Baseline')
            dialog.get_by_role('button',name='Confirm',exact=True).click()
            expect(dialog.get_by_role('alert')).to_have_text('Choose a status.')
            dialog.get_by_role('combobox',name='Status',exact=True).select_option('Draft')
            dialog.get_by_role('button',name='Confirm',exact=True).click()
            expect(grid.get_by_role('combobox',name='Budget version',exact=True)).to_have_text('1')
            expect(grid.locator('.plan-name')).to_have_text('Baseline')
            expect(grid.get_by_role('button',name='Save new version',exact=True)).to_be_disabled()
            grid.get_by_role('button',name='Edit',exact=True).click()
            page.screenshot(path=str(tmp_path/'finance-grid.png'),full_page=True)
            grid.get_by_role('button',name='Save new version',exact=True).click()
            expect(grid.get_by_role('dialog').get_by_role('textbox',name='Name',exact=True)).to_have_value('Baseline')
            grid.get_by_role('dialog').get_by_role('combobox',name='Status',exact=True).select_option('Approved')
            grid.get_by_role('dialog').get_by_role('button',name='Confirm',exact=True).click()
            expect(grid.get_by_role('combobox',name='Budget version',exact=True)).to_have_text('21')
            expect(grid.locator('.muted').first).to_contain_text('Approved')
            # Export retrieval is covered against the real authenticated endpoint separately.
            with page.expect_download() as download:
                grid.get_by_role('button',name='Export CSV',exact=True).click()
            assert re.fullmatch(re.escape(popup_server)+r'/downloads/finance/\d+/budget.csv',download.value.url)
            grid.get_by_role('button',name='Edit',exact=True).click()
            header=';'.join(['wbs_code','description',*map(str,range(2026,2041))])+'\n'
            invalid=header+'B;ignored;-1'+';'*14+'\n'
            grid.locator('input[type=file]').set_input_files({'name':'budget.csv','mimeType':'text/csv','buffer':invalid.encode()})
            expect(grid.get_by_role('alert').first).to_contain_text('Row 2, year 2026')
            expect(grid.get_by_role('textbox',name='1 WBS code',exact=True)).to_have_value('A.1')
            valid=header+'#NEW;ignored;77.25'+';'*14+'\n'
            grid.locator('input[type=file]').set_input_files({'name':'budget.csv','mimeType':'text/csv','buffer':valid.encode()})
            expect(grid.get_by_role('dialog')).to_contain_text('replaces the entire current/future grid')
            grid.get_by_role('dialog').get_by_role('button',name='Continue',exact=True).click()
            grid.get_by_role('dialog').get_by_role('combobox',name='Status',exact=True).select_option('Draft')
            grid.get_by_role('dialog').get_by_role('button',name='Confirm',exact=True).click()
            expect(grid.get_by_role('combobox',name='Budget version',exact=True)).to_have_text('321')
            grid.get_by_role('button',name='Edit',exact=True).click()
            expect(grid.get_by_role('textbox',name='1 WBS code',exact=True)).to_have_value('#NEW')
            expect(grid.get_by_role('textbox',name='1 2026',exact=True)).to_have_value('77.25')
            # Invalid clipboard batches and cancelled navigation preserve unsaved values.
            amount=grid.get_by_role('textbox',name='1 2026',exact=True)
            amount.click();paste(amount,'100\t-1')
            expect(grid.get_by_role('alert').first).to_contain_text('Row 1, year 2027')
            expect(amount).to_have_value('77.25')
            amount.fill('88.00')
            versions=grid.get_by_role('combobox',name='Budget version',exact=True)
            first_id=versions.locator('option').last.get_attribute('value')
            versions.select_option(first_id)
            grid.get_by_role('dialog').get_by_role('button',name='Cancel',exact=True).click()
            expect(amount).to_have_value('88.00')
            versions.select_option(first_id)
            grid.get_by_role('dialog').get_by_role('button',name='Discard changes',exact=True).click()
            grid.get_by_role('button',name='Edit',exact=True).click()
            expect(grid.get_by_role('textbox',name='1 WBS code',exact=True)).to_have_value('A.1')
            grid.get_by_role('button',name='Delete this plan',exact=True).click()
            grid.get_by_role('dialog').get_by_role('button',name='Confirm',exact=True).click()
            expect(grid.get_by_role('button',name='Delete this plan',exact=True)).to_be_hidden()
            assert versions.locator('option').count()==3
            grid.get_by_role('button',name='Edit',exact=True).click()
            expect(grid.get_by_role('button',name='Delete this plan',exact=True)).to_be_disabled()
            grid.get_by_role('button',name='Save new version',exact=True).click()
            grid.get_by_role('dialog').get_by_role('combobox',name='Status',exact=True).select_option('Proposed')
            grid.get_by_role('dialog').get_by_role('button',name='Confirm',exact=True).click()
            expect(versions).to_have_text('4321')
            grid.get_by_role('button',name='Edit',exact=True).click()
            expect(grid.get_by_role('textbox',name='1 WBS code',exact=True)).to_have_value('A.1')
            page.screenshot(path=str(tmp_path/'finance-grid.png'),full_page=True)
            expect(page.get_by_text('Shell runs: 1',exact=True)).to_be_visible()
            assert len(page.context.pages)==1
        finally:
            browser.close()


_EXIT_APP = _APP.replace("set_current_locale('en')", """
if fresh:
    for amount in ['42', '99']:
        service.save([{'code':'A.1','amounts':{'2026':amount}}],base_id=None,
                     status='Draft',name='Plan '+amount,year=2026)
set_current_locale('en')
""")


@pytest.mark.parametrize('popup_server', [_EXIT_APP], indirect=True, ids=['finance-exit-edit'])
def test_exit_edit_mode_restores_selected_plan_and_confirms_unsaved_changes(popup_server):
    """Read-only controls and explicit exit preserve the chosen saved version."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width':1500, 'height':1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(popup_server)
            grid = page.locator('.finance')
            edit = grid.get_by_role('button', name='Edit', exact=True)
            delete = grid.get_by_role('button', name='Delete this plan', exact=True)
            exit_edit = grid.get_by_role('button', name='Exit edit mode', exact=True)
            save = grid.get_by_role('button', name='Save new version', exact=True)
            expect(edit).to_be_visible(timeout=30000)
            expect(delete).to_be_hidden()
            expect(exit_edit).to_be_hidden()
            versions = grid.get_by_role('combobox', name='Budget version', exact=True)
            original_id = versions.locator('option').last.get_attribute('value')
            versions.select_option(original_id)
            expect(grid.locator('.plan-name')).to_have_text('Plan 42')
            edit.click()
            expect(delete).to_be_visible()
            expect(delete).to_be_enabled()
            expect(exit_edit).to_be_visible()
            exit_edit.click()
            expect(exit_edit).to_be_hidden()
            expect(delete).to_be_hidden()
            expect(save).to_be_disabled()
            expect(grid.get_by_role('dialog')).not_to_be_visible()
            edit.click()
            amount = grid.get_by_role('textbox', name='1 2026', exact=True)
            amount.fill('123')
            exit_edit.click()
            modal = grid.get_by_role('dialog')
            modal.get_by_role('button', name='Cancel', exact=True).click()
            expect(amount).to_have_value('123')
            expect(exit_edit).to_be_visible()
            expect(save).to_be_enabled()
            exit_edit.click()
            modal.get_by_role('button', name='Discard changes', exact=True).click()
            expect(exit_edit).to_be_hidden()
            expect(delete).to_be_hidden()
            expect(save).to_be_disabled()
            expect(versions).to_have_value(original_id)
            assert versions.locator('option').count() == 2
            assert grid.locator('tbody input').count() == 0
            edit.click()
            expect(amount).to_have_value('42.00')
            expect(grid.get_by_role('button', name='Import CSV', exact=True)).to_be_enabled()
            expect(page.get_by_text('Shell runs: 1', exact=True)).to_be_visible()
            assert errors == []
        finally:
            browser.close()


_READER_APP=_APP.replace("set_current_locale('en')", """
from app.application.services.access import AccessService, AuthorizationPolicy, SessionLimits
from app.application.services.business_access import BusinessAccess
from app.infrastructure.repositories.access import SqliteAccessGateway
from app.domain.access.models import VerifiedIdentity
import secrets
access=AccessService(SqliteAccessGateway(database),AuthorizationPolicy(lambda:1000,SessionLimits()),
                     'https://provider.example.test',lambda:secrets.token_urlsafe(32))
cookie=access.sign_in(VerifiedIdentity(access.issuer,'reader','','Reader',1000,100000,True))
actor=access.actor(cookie)
with access.gateway.transaction(write=True) as store:
    store.set_status(actor.user_id,'active',1000)
if fresh:
    service.save([{'code':'A.1','amounts':{'2026':'42'}}],base_id=None,status='Draft',name='Shared',year=2026)
service=create_finance_service(database,access=BusinessAccess(actor,access.policy))
service.today=lambda:date(2026,6,1)
set_current_locale('fr')
""")


@pytest.mark.parametrize('popup_server', [_READER_APP], indirect=True, ids=['finance-reader-fr'])
def test_active_reader_sees_the_shared_plan_with_editing_disabled(popup_server):
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={'width':1500,'height':1000})
            page.goto(popup_server)
            grid=page.locator('.finance')
            expect(grid.get_by_role('button',name='Enregistrer une nouvelle version',exact=True)).to_be_visible(timeout=30000)
            for name in ['Enregistrer une nouvelle version','Importer CSV','Modifier']:
                expect(grid.get_by_role('button',name=name,exact=True)).to_be_disabled()
            for name in ['Supprimer ce plan', 'Quitter le mode édition']:
                expect(grid.get_by_role('button',name=name,exact=True)).to_be_hidden()
            expect(grid.get_by_role('button',name='Exporter CSV',exact=True)).to_be_enabled()
            expect(grid.get_by_text('42.00',exact=True)).to_be_visible()
            assert grid.locator('tbody input').count()==0
        finally:
            browser.close()


_LARGE_APP=_APP.replace("set_current_locale('en')", """
if fresh:
    service.today=lambda:date(2021,6,1)
    service.save([{'code':f'WBS_{i}', 'amounts':{'2021':'1.00','2026':'2.00'}} for i in range(1000)],
                 base_id=None,status='Draft',name='Large plan',year=2021)
    service.today=lambda:date(2026,6,1)
set_current_locale('en')
""")


@pytest.mark.parametrize('popup_server', [_LARGE_APP], indirect=True, ids=['1000-wbs'])
def test_large_finance_grid_virtualizes_rows_and_preserves_history_on_paste(popup_server, tmp_path):
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={'width':1500,'height':1000})
            page.goto(popup_server)
            grid=page.locator('.finance')
            grid.get_by_role('button',name='Edit',exact=True).click(timeout=30000)
            expect(grid.get_by_role('textbox',name='1 WBS code',exact=True)).to_be_visible(timeout=30000)
            assert grid.locator('tbody tr[data-row]').count()<=28
            viewport=grid.locator('.viewport')
            elapsed=viewport.evaluate("""async node=>{const start=performance.now();node.scrollTop=500*36;
                await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
                return performance.now()-start;}""")
            expect(grid.get_by_role('textbox',name='501 WBS code',exact=True)).to_be_visible()
            assert viewport.evaluate('node=>node.scrollLeft')==550
            assert grid.locator('tbody tr[data-row]').count()<=28
            # Verify a multi-cell edit in historical columns is rejected atomically.
            viewport.evaluate('node=>{node.scrollTop=0;node.scrollLeft=0;}')
            past=grid.locator('tbody tr[data-row="0"] td.past').first
            expect(past).to_have_text('1.00')
            past.click();paste(past,'999\t999')
            expect(grid.get_by_role('alert').first).to_contain_text('read-only')
            expect(past).to_have_text('1.00')
            code=grid.get_by_role('textbox',name='1 WBS code',exact=True)
            code.fill('RENAMED');code.press('Tab')
            expect(grid.get_by_role('textbox',name='1 WBS code',exact=True)).to_have_value('RENAMED')
            expect(grid.locator('tbody tr[data-row="0"] td.past').first).to_have_text('')
            expect(grid.get_by_text('1001 WBS rows',exact=True)).to_be_visible()
            expect(page.get_by_text('Shell runs: 1',exact=True)).to_be_visible()
            (tmp_path/'finance-1000-rows.json').write_text(json.dumps({'scroll_render_ms':elapsed,'rendered_rows':grid.locator('tbody tr[data-row]').count(),'shell_runs':1}),encoding='utf-8')
            assert elapsed<1000
        finally:
            browser.close()


@pytest.mark.parametrize('popup_server', [_APP], indirect=True, ids=['spreadsheet-entry'])
def test_blank_rows_grow_keyboard_navigation_and_missing_code_validation(popup_server):
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={'width':1500,'height':1000})
            page.goto(popup_server)
            grid=page.locator('.finance')
            grid.get_by_role('button',name='Edit',exact=True).click(timeout=30000)
            first=grid.get_by_role('textbox',name='1 WBS code',exact=True)
            expect(first).to_be_visible(timeout=30000)
            first.fill('A');first.press('Tab')
            amount=grid.get_by_role('textbox',name='1 2026',exact=True)
            expect(amount).to_be_focused()
            amount.press('Enter')
            expect(grid.get_by_role('textbox',name='2 2026',exact=True)).to_be_focused()
            page.keyboard.press('Shift+Enter')
            expect(amount).to_be_focused()
            amount.press('Shift+Tab');expect(first).to_be_focused()
            first.fill('');first.press('Tab')
            expect(grid.locator('tr[data-row="0"]')).to_have_class('unused')
            amount.fill('0')
            grid.get_by_role('button',name='Save new version',exact=True).click()
            expect(grid.get_by_role('alert').first).to_contain_text('Row 1')
            first.fill('A');first.press('Tab');amount.fill('')
            viewport=grid.locator('.viewport')
            viewport.evaluate('node=>node.scrollTop=10000')
            last=grid.get_by_role('textbox',name='25 WBS code',exact=True)
            expect(last).to_be_visible()
            last.fill('LAST');last.press('Enter')
            expect(grid.get_by_role('textbox',name='26 WBS code',exact=True)).to_be_focused()
            assert viewport.evaluate('node=>node.scrollHeight')>=35*36
            expect(grid.get_by_text('2 WBS rows',exact=True)).to_be_visible()
            expect(page.get_by_text('Shell runs: 1',exact=True)).to_be_visible()
        finally:
            browser.close()
