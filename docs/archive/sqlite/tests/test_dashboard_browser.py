"""Real dashboard charts, issue popup, paging and browser-local session activity."""

import json
import re
import time

import pytest

from tests.test_dialog_browser import popup_server as popup_server, expect, sync_playwright


_APP = '''
from pathlib import Path
from contextlib import closing
from datetime import date
import streamlit as st
from app.infrastructure.database.schema_init import init_db
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.operator_context import deployment_access
from app.main import create_dashboard_service, create_finance_service
from app.presentation.pages.dashboard import render_dashboard
from app.presentation.i18n import set_current_locale

st.set_page_config(layout='wide')
database=str(Path(__file__).with_suffix('.db'))
if not Path(database).exists():
    init_db(database)
    with closing(get_db(database)) as conn,conn:
        conn.executemany('INSERT INTO project(id,name) VALUES(?,?)', [(i,f'Project {i:04d}') for i in range(1,1001)])
        conn.execute("INSERT INTO wbs(id,code,description) VALUES(1,'A','Example')")
        conn.execute('INSERT INTO project_wbs VALUES(1,1,50)')
        conn.execute("INSERT INTO resource_pool(id,name,capacity_fte) VALUES(1,'Pool A',1),(2,'Pool B',1)")
        conn.executemany("INSERT INTO resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date) VALUES(?,?,?,'2026-01-01','2026-03-31')",[(1,1,1),(1,2,2),(2,1,1),(2,2,1)])
        blocker=conn.execute("SELECT id FROM project_event_type WHERE system_code='blocking_point'").fetchone()[0]
        conn.execute("INSERT INTO project_log_event(project_id,title,description,comment,event_type_id,status) VALUES(1,'Delivery blocked','First line'||char(10)||'Second line','Read only',?,'active')",(blocker,))
    finance=create_finance_service(database,access=deployment_access())
    finance.today=lambda:date(2026,6,1)
    finance.save([{'code':'A','amounts':{'2026':'100.01','2027':'200'}}],base_id=None,name='Approved plan',status='Approved',year=2026)
service=create_dashboard_service(database,access=deployment_access())
service.today=lambda:date(2026,6,1)
set_current_locale('en')
st.session_state['shell_runs']=st.session_state.get('shell_runs',0)+1
st.caption('Shell runs: '+str(st.session_state['shell_runs']))
if st.session_state.get('nav_redirect'):
    st.write('Planning projects: '+str(st.session_state['dashboard_planning_projects']))
else:
    render_dashboard(service)
'''


_SHARED_BUDGET_APP = _APP.replace('INSERT INTO project_wbs VALUES(1,1,50)',
                                 'INSERT INTO project_wbs VALUES(1,1,50),(2,1,25)')


@pytest.mark.parametrize('popup_server', [_SHARED_BUDGET_APP], indirect=True, ids=['distinct-budget-shares'])
def test_finance_curve_uses_selected_project_share(popup_server):
    """Check actual chart values when two projects share one approved WBS."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width':1500,'height':1200})
            page.goto(popup_server)
            page.locator('.st-key-dashboard_project_list summary').click(timeout=30000)
            table = page.locator('.st-key-dashboard_project_table .viewport')
            expect(table.locator('tr[data-project-id="1"]')).to_be_visible(timeout=30000)
            points = page.locator('[data-testid=stVegaLiteChart] .mark-symbol.role-mark path')
            for project_id, expected in [(1,'50.01'),(2,'25.00')]:
                table.locator(f'tr[data-project-id="{project_id}"]').click()
                expect(page.get_by_text('1 matching projects',exact=True)).to_be_visible()
                expect(points).to_have_count(2)
                expect(points.first).to_have_attribute('aria-label', re.compile(': '+re.escape(format(float(expected),'g'))+';'))
                points.first.hover()
                expect(page.locator('#vg-tooltip-element')).to_contain_text(expected)
                table.locator(f'tr[data-project-id="{project_id}"]').click()
                expect(page.get_by_text('1000 matching projects',exact=True)).to_be_visible()
            expect(page.get_by_text('Shell runs: 1',exact=True)).to_be_visible()
        finally:
            browser.close()


@pytest.mark.parametrize('popup_server', [_APP], indirect=True, ids=['dashboard-1000'])
def test_dashboard_charts_paging_and_read_only_issues_do_not_rerun_shell(popup_server,tmp_path):
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={'width':1500,'height':1200})
            start=time.perf_counter();page.goto(popup_server)
            expect(page.locator('.st-key-dashboard_issue_count button:visible')).to_be_visible(timeout=30000)
            expect(page.locator('[data-testid=stVegaLiteChart]').first).to_be_visible(timeout=30000)
            initial=time.perf_counter()-start
            expect(page.get_by_text('1000 matching projects',exact=True)).to_be_visible()
            expect(page.locator('.st-key-dashboard_project_list details')).not_to_have_attribute('open', '')
            page.locator('.st-key-dashboard_project_list summary').click()
            table=page.locator('.st-key-dashboard_project_table .viewport')
            expect(table.locator('tr[data-project-id="1"]')).to_be_visible()
            assert table.locator('tr[data-project-id]').count()<=12
            table.locator('tr[data-project-id="2"]').click()
            expect(page.get_by_text('1 matching projects',exact=True)).to_be_visible()
            expect(table.locator('tr[data-project-id="2"]')).to_have_attribute('aria-selected','true')
            expect(page.locator('.st-key-dashboard_issue_count button:visible')).to_be_disabled()
            expect(page.locator('.st-key-dashboard_issue_card')).to_contain_text('0 Active Issues')
            expect(page.get_by_text('0 Active Issues',exact=True)).to_have_css('color','rgb(0, 0, 0)')
            expect(page.locator('.st-key-dashboard_issue_count [data-testid=stIconMaterial]').first).to_have_css('color','rgb(35, 147, 76)')
            expect(page.get_by_role('dialog')).to_have_count(0)
            expect(page.locator('[data-testid=stVegaLiteChart] .mark-symbol.role-mark path')).to_have_count(0)
            expect(page.get_by_text('Shell runs: 1',exact=True)).to_be_visible()
            table.locator('tr[data-project-id="2"]').press('Enter')
            expect(page.get_by_text('1000 matching projects',exact=True)).to_be_visible()
            expect(page.locator('.st-key-dashboard_issue_count button:visible')).to_be_enabled()
            expect(page.locator('.st-key-dashboard_issue_card')).to_contain_text('1 Active Issues')
            expect(page.get_by_text('1 Active Issues',exact=True)).to_have_css('color','rgb(223, 139, 22)')
            chart=page.get_by_test_id('stVegaLiteChart')
            chart.evaluate("node=>node.dataset.mountCheck='retained'")
            start=time.perf_counter();table.evaluate('node=>node.scrollTop=3500')
            expect(table.locator('tr[data-project-id="101"]')).to_be_visible()
            assert table.evaluate('node=>node.scrollTop')==3500
            expect(chart).to_have_attribute('data-mount-check','retained')
            paging=time.perf_counter()-start
            summary=page.get_by_text('1000 matching projects',exact=True)
            summary.click()
            expect(table).not_to_be_visible()
            expect(summary).to_be_visible()
            summary.click()
            expect(page.get_by_text('Shell runs: 1',exact=True)).to_be_visible()
            page.locator('.st-key-dashboard_issue_count button:visible').click()
            dialog=page.get_by_role('dialog')
            expect(dialog.get_by_text('Delivery blocked',exact=True)).to_be_visible()
            expect(dialog.get_by_text('First line\nSecond line',exact=True)).to_be_visible()
            assert dialog.locator('input,textarea').count()==0
            assert dialog.get_by_role('button',name='Edit',exact=True).count()==0
            page.keyboard.press('Escape')
            expect(dialog).not_to_be_visible()
            page.get_by_role('button',name='Flexible filters').click()
            field=page.get_by_role('combobox',name='Filter fields',exact=True)
            field.fill('Project')
            page.get_by_role('option',name='Project',exact=True).click()
            project=page.get_by_role('combobox',name='Project',exact=True)
            project.fill('Project 0001')
            start=time.perf_counter();page.get_by_role('option',name='Project 0001',exact=True).click()
            expect(page.get_by_text('1 matching projects',exact=True)).to_be_visible()
            filtering=time.perf_counter()-start
            page.keyboard.press('Escape')
            page.get_by_test_id('stPopoverButton').click()
            expect(field).not_to_be_visible()
            expect(page.get_by_text('Shell runs: 1',exact=True)).to_be_visible()
            point = page.locator('[data-testid=stVegaLiteChart]').first.locator('.mark-symbol path').first
            point.hover()
            expect(page.locator('#vg-tooltip-element')).to_contain_text('50.01')
            page.get_by_role('heading', name='Finance overview', exact=True).hover()
            expect(page.get_by_role('heading', name='Dashboard', exact=True)).to_have_count(0)
            expect(page.locator('.resource-chart [data-today="2026-06-01"]')).to_have_count(1)
            expect(page.locator('.resource-chart .legend')).to_contain_text('Total pools capacity')
            resource = page.locator('.resource-chart')
            expect(resource.locator('[data-axis-title="overallocation"]')).to_have_attribute('transform',re.compile(r'rotate\(-90\)'))
            expect(resource.locator('[data-axis-title="capacity"]')).to_have_attribute('transform',re.compile(r'rotate\(90\)'))
            assert resource.locator('[data-quarter]').count()==48
            expect(resource.locator('[data-quarter="2024-Q1"]')).to_have_count(1)
            expect(resource.locator('[data-quarter="2035-Q4"]')).to_have_count(1)
            assert all(re.fullmatch(r'\d+', text) for text in resource.locator('[data-axis]').all_text_contents())
            for axis in ('overallocation','capacity'):
                ticks=resource.locator(f'[data-axis="{axis}"]').all_text_contents()
                assert len(ticks)==len(set(ticks))
            resource.locator('[data-quarter="2026-Q1"]').hover()
            expect(resource.get_by_role('tooltip')).to_contain_text('Overallocation: 3.0')
            expect(resource.get_by_role('tooltip')).to_contain_text('Total pools capacity: 2.0')
            assert resource.locator('.legend').bounding_box()['x'] >= resource.locator('svg').bounding_box()['x']+resource.locator('svg').bounding_box()['width']
            expect(page.locator('.st-key-dashboard_issue_card')).to_contain_text('Active Issues')
            issue_icon=page.locator('.st-key-dashboard_issue_count [data-testid=stIconMaterial]').first
            assert issue_icon.evaluate('node=>parseFloat(getComputedStyle(node).fontSize)')>=48
            expect(issue_icon).to_have_css('color','rgb(223, 139, 22)')
            icon_box=issue_icon.bounding_box()
            card_box=page.locator('.st-key-dashboard_issue_card').bounding_box()
            assert abs(icon_box['x']+icon_box['width']/2-card_box['x']-card_box['width']/2)<3
            expect(page.get_by_text('1 matching projects',exact=True)).to_be_visible()
            expect(table.locator('tr[data-project-id="2"]')).to_have_count(0)
            expect(table.locator('tr[data-project-id="1"]')).to_be_visible()
            page.get_by_role('heading',name='Finance overview',exact=True).hover()
            page.screenshot(path=str(tmp_path/'dashboard.png'),full_page=True,animations='disabled')
            (tmp_path/'dashboard-timing.json').write_text(json.dumps({'initial_seconds':initial,'paging_seconds':paging,'filter_seconds':filtering,'shell_runs':1}),encoding='utf-8')
            quarter=page.locator('.resource-chart [data-quarter="2026-Q1"]')
            quarter.click(button='right')
            page.get_by_role('menuitem', name='Planning & milestones: consuming projects').click()
            expect(page.get_by_text('Planning projects: [1, 2]', exact=True)).to_be_visible()
        finally:
            browser.close()
