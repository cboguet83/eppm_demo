"""Visual financial stacks, legends, metric order and unclipped vertical titles."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from app.main import create_finance_service
from app.runtime import RuntimeResources
from app.presentation.i18n import load_locale_catalog
from tests.postgresql.browser import native_server
from tests.postgresql.dashboard_browser import _SCREEN
from tests.postgresql.test_financial_transactions import service
from tests.test_financial_transactions import transaction

playwright_api = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = playwright_api.expect, playwright_api.sync_playwright


def test_financial_stacks_legend_ratios_and_chart_axis_padding(authorized, tmp_path):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='In Progress'")
        connection.execute("INSERT INTO eppm.wbs(id,code) VALUES(1,'A')")
        connection.execute('INSERT INTO eppm.project_wbs VALUES(1,1,100)')
    finance = create_finance_service(RuntimeResources(authorized.database, authorized.key),
                                     access=authorized.binding(4).access)
    finance.today = lambda: date(2026, 6, 1)
    finance.save([{'code': 'A', 'amounts': {'2026': '100'}}],
                 base_id=None, name='Delivery budget', status='Approved', year=2026)
    for kind, amount in [('ACTUAL', '20'), ('COMMITMENT', '130')]:
        service(authorized).create(transaction(financial_record_type=kind, amount=Decimal(amount)))
    screen = _SCREEN.replace("set_current_locale('en')",
                             "set_current_locale(st.selectbox('Test language', ['en', 'fr', 'de', 'lb', 'pt']))")
    with native_server(authorized, tmp_path, screen) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1600, 'height': 1200})
            page.goto(server.origin)
            chart = page.locator('.st-key-dashboard_finance_chart')
            expect(chart).to_be_visible(timeout=30000)
            expect(chart.locator('.legend')).to_contain_text('Approved — Delivery budget')
            expect(chart.locator('[data-financial-type=actual]')).to_have_attribute('fill', '#C41049')
            expect(chart.locator('[data-financial-type=commitment]')).to_have_attribute('fill', '#6D6E70')
            bar_box = chart.locator('[data-financial-type=actual]').bounding_box()
            point_box = chart.locator('circle').first.bounding_box()
            assert abs(bar_box['x'] + bar_box['width'] / 2 - point_box['x'] - point_box['width'] / 2) < 1
            chart.locator('[data-financial-type=actual]').hover()
            expect(chart.get_by_role('tooltip')).to_contain_text('Actual: 0 kEUR')
            expect(chart.get_by_role('tooltip')).to_contain_text('Commitment: 0 kEUR')
            expect(chart.locator('[data-axis-title=finance]')).to_have_text('Budget (kEUR)')
            financial_year = chart.locator('[data-year="2026"]').bounding_box()
            for metric in ('allocation', 'overallocation'):
                resource_year = page.locator(f'.st-key-dashboard_resource_chart_{metric} [data-year="2026"]').bounding_box()
                assert abs(financial_year['x'] + financial_year['width'] / 2
                           - resource_year['x'] - resource_year['width'] / 2) < 1
            assert chart.locator('[data-axis=finance]').all_text_contents() == ['0', '0.1', '0.2', '0.3', '0.4']
            page.get_by_role('heading', name='Finance overview', exact=True).hover()
            cards = [page.locator('.st-key-' + key) for key in (
                'dashboard_late_card', 'dashboard_actual_ratio_card',
                'dashboard_committed_ratio_card', 'dashboard_issue_card')]
            expect(cards[1]).to_contain_text('20.0%')
            expect(cards[2]).to_contain_text('150.0%')
            positions = [card.bounding_box()['y'] for card in cards]
            assert positions == sorted(positions)
            for key in ('dashboard_finance_chart', 'dashboard_resource_chart_allocation'):
                root = page.locator('.st-key-' + key + ' .resource-chart')
                expect(root).to_have_css('padding-left', '5px')
                title = root.locator('[data-axis-title]')
                assert title.bounding_box()['x'] >= root.bounding_box()['x']
            page.screenshot(path=str(Path('.local/dashboard-financial-chart.png').resolve()), full_page=True)
            for locale in ('fr', 'de', 'lb', 'pt', 'en'):
                page.get_by_role('combobox', name='Test language').click()
                page.get_by_role('option', name=locale, exact=True).click()
                labels = load_locale_catalog(locale)['dashboard']
                expect(cards[0]).to_contain_text(labels['late_projects'])
                expect(cards[1]).to_contain_text(labels['actual_ratio'])
                chart.locator('[data-financial-type=actual]').hover()
                expect(chart.get_by_role('tooltip')).to_contain_text(labels['actual'] + ': 0 kEUR')
                expect(chart.get_by_role('tooltip')).to_contain_text(labels['commitment'] + ': 0 kEUR')
        finally:
            browser.close()
