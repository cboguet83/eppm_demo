"""Native dashboard organization button selection and cascading behavior."""

from datetime import date
import re

import psycopg

from app.main import create_finance_service
from app.runtime import RuntimeResources
from tests.postgresql.browser import native_server
from tests.postgresql.dashboard_browser import _SCREEN
from tests.postgresql.test_dashboard_organization_filters import seed_organization
from tests.test_dialog_browser import expect, sync_playwright


def test_dashboard_organization_buttons_cascade_and_keep_status_default(authorized, tmp_path):
    seed_organization(authorized)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.wbs(id,code) VALUES (1,'ORG')")
        connection.execute('INSERT INTO eppm.project_wbs(project_id,wbs_id,percentage) VALUES (1,1,25),(2,1,75)')
    finance = create_finance_service(RuntimeResources(authorized.database, authorized.key), access=authorized.binding(4).access)
    finance.today = lambda: date(2026, 6, 1)
    finance.save([{'code': 'ORG', 'amounts': {'2026': '100.00'}}],
                 base_id=None, name='Organization budget', status='Approved', year=2026)
    with native_server(authorized, tmp_path, _SCREEN) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width':1500, 'height':1100})
            page.goto(server.origin)
            services = page.locator('.st-key-dashboard_filter_service')
            expect(services.get_by_role('button', name='Service A', exact=True)).to_be_visible(timeout=30000)
            expect(services.get_by_role('button', name='Service B', exact=True)).to_be_visible()
            expect(services.get_by_role('button', name='Private service', exact=True)).to_be_visible()
            expect(services.get_by_role('button', name='Not assigned', exact=True)).to_be_visible()
            expect(page.locator('.st-key-dashboard_filter_status')).to_contain_text('In Progress')
            count = lambda value: expect(page.get_by_text(f'{value} matching projects', exact=True)).to_be_visible()
            count(3)
            budget_point = page.locator('.st-key-dashboard_finance_chart circle').first
            expect(budget_point).to_have_attribute('aria-label', re.compile(r': 100\.00'))
            divisions = page.locator('details').filter(has=page.get_by_text('Divisions', exact=True))
            teams = page.locator('details').filter(has=page.get_by_text('Teams', exact=True))
            expect(divisions).not_to_have_attribute('open', '')
            expect(teams).not_to_have_attribute('open', '')
            page.screenshot(path=str(tmp_path / 'organization-panel-default.png'), full_page=True)
            services.get_by_role('button', name='Service A', exact=True).click()
            count(1)
            expect(budget_point).to_have_attribute('aria-label', re.compile(r': 25\.00'))
            expect(page.locator('.st-key-dashboard_filter_org_manager')).to_contain_text('Alice Manager')
            services.get_by_role('button', name='Service B', exact=True).click(modifiers=['Control'])
            count(2)
            expect(budget_point).to_have_attribute('aria-label', re.compile(r': 100\.00'))
            services.get_by_role('button', name='Service A', exact=True).click()
            count(1)
            divisions.locator('summary').click()
            division_choices = page.locator('.st-key-dashboard_filter_division')
            expect(division_choices).to_contain_text('Division B')
            expect(division_choices).not_to_contain_text('Division A')
            division_choices.get_by_role('button', name='Division B', exact=True).click()
            teams.locator('summary').click()
            expect(page.locator('.st-key-dashboard_filter_org_team')).to_contain_text('Team B')
            page.locator('.st-key-dashboard_filter_org_team').get_by_role('button', name='Team B', exact=True).click()
            services.get_by_role('button', name='Service A', exact=True).click()
            expect(division_choices).to_contain_text('Division A')
            services.get_by_role('button', name='Service B', exact=True).click()
            count(1)
            expect(division_choices).to_contain_text('Division A')
            expect(division_choices).not_to_contain_text('Division B')
            services.get_by_role('button', name='Service A', exact=True).click()
            expect(division_choices).to_contain_text('Division B')
            services.get_by_role('button', name='Not assigned', exact=True).click()
            count(1)
            expect(page.locator('.st-key-dashboard_filter_org_manager')).to_contain_text('Not assigned')
            page.locator('.st-key-dashboard_clear button').click()
            count(3)
            expect(page.locator('.st-key-dashboard_filter_status')).to_contain_text('In Progress')
            services.get_by_role('button', name='Service A', exact=True).focus()
            page.keyboard.press('Space')
            count(1)
            services.get_by_role('button', name='Service A', exact=True).focus()
            page.keyboard.press('Space')
            count(3)
            page.locator('.st-key-dashboard_filter_org_manager').get_by_role('button', name='Alice Manager', exact=True).click()
            count(1)
            page.screenshot(path=str(tmp_path / 'organization-panel.png'), full_page=True)
        finally:
            browser.close()
