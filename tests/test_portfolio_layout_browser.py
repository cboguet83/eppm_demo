"""Master-page spacing and filter styling with real browser layout and CSS."""

import pytest

from tests.test_dialog_browser import popup_server as popup_server, expect, sync_playwright


_DECIMAL_APP = '''
from decimal import Decimal
import json
import streamlit as st
from app.presentation.components.portfolio_table import portfolio_project_table

amount = Decimal('9007199254740993.01234567890123456789')
request = st.session_state.get('exact_portfolio', {}).get('request') or {}
columns = [{'key': 'planned_budget', 'label': 'Budget', 'format': 'currency'}]
facet = None
if request.get('kind') == 'facet':
    facet = {'column': 'planned_budget', 'search': request.get('search', ''), 'format': 'currency',
             'stats': [['Minimum', amount]], 'values': [{'value': amount, 'count': 1}], 'has_more': False}
portfolio_project_table([{'project_id': 1, 'planned_budget': amount}], columns, None,
    key='exact_portfolio', page_info={'context': 'exact', 'total': 1, 'offset': 0, 'page_size': 100,
        'query': request.get('query', {}), 'request_id': request.get('nonce'), 'facet': facet})
st.code(json.dumps(request.get('query', {})))
'''


@pytest.mark.parametrize('popup_server', [_DECIMAL_APP], indirect=True, ids=['decimal-facets'])
def test_exact_decimal_facet_choice_round_trips_through_the_real_component(popup_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 1500, 'height': 1100})
            page.goto(popup_server)
            table = page.locator('.st-key-exact_portfolio')
            expect(table.locator('tbody tr').first).to_be_visible(timeout=30000)
            table.locator('.filter-button').first.click()
            menu = table.locator('.filter-menu')
            choice = menu.get_by_role('checkbox').first
            expect(choice).to_be_visible()
            choice.uncheck()
            menu.get_by_role('button', name='Apply', exact=True).click()
            expect(page.get_by_test_id('stCode')).to_contain_text('9007199254740993.01234567890123456789')
            expect(page.get_by_test_id('stException')).to_have_count(0)
        finally:
            browser.close()
