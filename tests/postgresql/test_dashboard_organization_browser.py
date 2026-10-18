"""Native dashboard organization button selection and cascading behavior."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
import re
from typing import TYPE_CHECKING

import psycopg
import pytest

from app.main import create_finance_service
from app.runtime import RuntimeResources
from tests.postgresql.browser import native_server
from tests.postgresql.browser_completion import ScriptCompletion
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.dashboard_browser import _SCREEN
from tests.postgresql.test_dashboard_organization_filters import seed_organization
from tests.postgresql.test_shared_project_filters_browser import _completed_filter_run
from tests.test_dialog_browser import expect, sync_playwright


if TYPE_CHECKING:
    from playwright.sync_api import Page


@contextmanager
def _completed_action(
    page: 'Page', completion: ScriptCompletion,
    services: tuple[str, ...] | None = None,
) -> Iterator[None]:
    """Wait for server completion and any expected service-button redraw."""
    with _completed_filter_run(
        page, completion, prefix='Dashboard test run: ',
    ):
        yield
    if services is not None:
        pressed = page.locator(
            '.st-key-dashboard_filter_service_buttons button[aria-pressed="true"]',
        )
        expect(pressed).to_have_text(list(services))


def _organization_screen(*, delay_services: bool) -> str:
    """Instrument completion and optionally delay clearing service buttons."""
    screen = '''
import streamlit as st
from app.application.services.dashboard import DashboardService
import app.presentation.pages.dashboard as dashboard_module
if not hasattr(dashboard_module, '_test_original_dashboard'):
    dashboard_module._test_original_dashboard = dashboard_module.render_dashboard.__wrapped__
    @st.fragment(key='dashboard')
    def completed_dashboard(service: DashboardService) -> None:
        """Render the original dashboard and acknowledge fragment completion."""
        dashboard_module._test_original_dashboard(service)
        st.session_state['dashboard_test_runs'] = st.session_state.get('dashboard_test_runs', 0) + 1
        st.html('<style>.st-key-dashboard_test_completion{display:none!important}</style>')
        with st.container(key='dashboard_test_completion'):
            st.caption('Dashboard test run: ' + str(st.session_state['dashboard_test_runs']))
    dashboard_module.render_dashboard = completed_dashboard
'''
    if delay_services:
        screen += '''
import importlib
panel_module = importlib.import_module('app.presentation.components.organization_filter_panel')
original_js = panel_module._BUTTONS_JS.replace('export default function(', 'function renderButtons(')
panel_module._BUTTONS_JS = original_js + """
export default function(args) {
    let cleanup;
    const delay = args.data.title === 'Services' && args.data.selected.length === 0 ? 1000 : 0;
    const timer = setTimeout(() => { cleanup = renderButtons(args); }, delay);
    return () => { clearTimeout(timer); if (cleanup) cleanup(); };
}
"""
'''
    return screen + _SCREEN


@pytest.mark.parametrize('delay_services', [False, True], ids=['immediate', 'delayed-services'])
def test_dashboard_organization_buttons_cascade_and_keep_status_default(
    authorized: AuthorizedFixture, tmp_path: Path, delay_services: bool,
) -> None:
    """Check organization filtering after acknowledged component updates.

    Args:
        authorized: Isolated database, accounts and restricted runtime access.
        tmp_path: Private directory for browser sources, logs and screenshots.
        delay_services: Delay cleared buttons to expose lost keyboard focus.
    """
    seed_organization(authorized)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.wbs(id,code) VALUES (1,'ORG')")
        connection.execute('INSERT INTO eppm.project_wbs(project_id,wbs_id,percentage) VALUES (1,1,25),(2,1,75)')
    finance = create_finance_service(RuntimeResources(authorized.database, authorized.key), access=authorized.binding(4).access)
    finance.today = lambda: date(2026, 6, 1)
    finance.save([{'code': 'ORG', 'amounts': {'2026': '100000.00'}}],
                 base_id=None, name='Organization budget', status='Approved', year=2026)
    screen = _organization_screen(delay_services=delay_services)
    with native_server(authorized, tmp_path, screen) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width':1500, 'height':1100})
            completion = ScriptCompletion(page)
            page.goto(server.origin)
            services = page.locator('.st-key-dashboard_filter_service_buttons')
            expect(services.get_by_role('button', name='Service A', exact=True)).to_be_visible(timeout=30000)
            expect(services.get_by_role('button', name='Service B', exact=True)).to_be_visible()
            expect(services.get_by_role('button', name='Private service', exact=True)).to_be_visible()
            expect(services.get_by_role('button', name='Not assigned', exact=True)).to_be_visible()
            expect(page.locator('.st-key-dashboard_filter_status')).to_contain_text('In Progress')
            count = lambda value: expect(page.get_by_text(f'{value} matching projects', exact=True)).to_be_visible()
            count(3)
            budget_point = page.locator('.st-key-dashboard_finance_chart circle').first
            expect(budget_point).to_have_attribute('aria-label', re.compile(r': 100 kEUR$'))
            divisions = page.locator('details').filter(has=page.get_by_text('Divisions', exact=True))
            teams = page.locator('details').filter(has=page.get_by_text('Teams', exact=True))
            expect(divisions).not_to_have_attribute('open', '')
            expect(teams).not_to_have_attribute('open', '')
            managers = page.locator('details').filter(has=page.get_by_text('Project managers', exact=True))
            expect(managers).not_to_have_attribute('open', '')
            expect(page.get_by_text('Services', exact=True)).not_to_be_visible()
            assert page.locator('.st-key-organization_service_frame').evaluate('(element) => getComputedStyle(element).paddingTop') == '2px'
            assert float(page.locator('.stMainBlockContainer').evaluate('(element) => getComputedStyle(element).paddingTop').removesuffix('px')) <= 1
            assert divisions.bounding_box()['height'] == 24
            assert teams.bounding_box()['y'] - (divisions.bounding_box()['y'] + 24) == 8
            page.screenshot(path=str(tmp_path / 'organization-panel-default.png'), full_page=True)
            with _completed_action(page, completion, services=('Service A',)):
                services.get_by_role('button', name='Service A', exact=True).click()
            count(1)
            expect(services.get_by_role('button', name='Service A', exact=True)).to_have_attribute('title', 'Ctrl+click to select multiple options.')
            with _completed_action(page, completion, services=('Service B',)):
                services.get_by_role('button', name='Service B', exact=True).click()
            expect(services.get_by_role('button', name='Service A', exact=True)).to_have_attribute('aria-pressed', 'false')
            expect(services.get_by_role('button', name='Service B', exact=True)).to_have_attribute('aria-pressed', 'true')
            with _completed_action(page, completion, services=('Service A',)):
                services.get_by_role('button', name='Service A', exact=True).click()
            expect(services.get_by_role('button', name='Service B', exact=True)).to_have_attribute('aria-pressed', 'false')
            expect(budget_point).to_have_attribute('aria-label', re.compile(r': 25 kEUR$'))
            expect(page.locator('.st-key-dashboard_filter_org_manager_buttons')).to_contain_text('Alice Manager')
            with _completed_action(page, completion, services=('Service A', 'Service B')):
                services.get_by_role('button', name='Service B', exact=True).click(modifiers=['Control'])
            count(2)
            expect(budget_point).to_have_attribute('aria-label', re.compile(r': 100 kEUR$'))
            with _completed_action(page, completion, services=('Service B',)):
                services.get_by_role('button', name='Service A', exact=True).click(modifiers=['Control'])
            count(1)
            with _completed_action(page, completion):
                divisions.locator('summary').click()
            assert divisions.locator('[data-testid="stExpanderDetails"]').evaluate('(element) => getComputedStyle(element).paddingBottom') == '2px'
            division_choices = page.locator('.st-key-dashboard_filter_division_buttons')
            expect(division_choices).to_contain_text('Division B')
            expect(division_choices).not_to_contain_text('Division A')
            with _completed_action(page, completion):
                division_choices.get_by_role('button', name='Division B', exact=True).click()
            with _completed_action(page, completion):
                teams.locator('summary').click()
            expect(page.locator('.st-key-dashboard_filter_org_team_buttons')).to_contain_text('Team B')
            with _completed_action(page, completion):
                page.locator('.st-key-dashboard_filter_org_team_buttons').get_by_role('button', name='Team B', exact=True).click()
            with _completed_action(page, completion, services=('Service A', 'Service B')):
                services.get_by_role('button', name='Service A', exact=True).click(modifiers=['Control'])
            expect(division_choices).to_contain_text('Division A')
            with _completed_action(page, completion, services=('Service A',)):
                services.get_by_role('button', name='Service B', exact=True).click(modifiers=['Control'])
            count(1)
            expect(division_choices).to_contain_text('Division A')
            expect(division_choices).not_to_contain_text('Division B')
            with _completed_action(page, completion, services=()):
                services.get_by_role('button', name='Service A', exact=True).click()
            expect(division_choices).to_contain_text('Division B')
            with _completed_action(page, completion, services=('Not assigned',)):
                services.get_by_role('button', name='Not assigned', exact=True).click()
            count(1)
            expect(page.locator('.st-key-dashboard_filter_org_manager_buttons')).to_contain_text('Not assigned')
            with _completed_action(page, completion, services=()):
                page.locator('.st-key-dashboard_clear button').click()
            count(3)
            expect(page.locator('.st-key-dashboard_filter_status')).to_contain_text('In Progress')
            services.get_by_role('button', name='Service A', exact=True).focus()
            if delay_services:
                # Fault injection: a user pauses while the queued redraw finishes.
                page.wait_for_timeout(1200)
            with _completed_action(page, completion, services=('Service A',)):
                page.keyboard.press('Space')
            count(1)
            services.get_by_role('button', name='Service A', exact=True).focus()
            with _completed_action(page, completion, services=()):
                page.keyboard.press('Space')
            count(3)
            with _completed_action(page, completion):
                managers.locator('summary').click()
            with _completed_action(page, completion):
                page.locator('.st-key-dashboard_filter_org_manager_buttons').get_by_role('button', name='Alice Manager', exact=True).click()
            count(1)
            page.screenshot(path=str(tmp_path / 'organization-panel.png'), full_page=True)
        finally:
            browser.close()


def test_dashboard_filter_spacing_in_full_shell(authorized, tmp_path):
    """Measure actual shell whitespace rather than the standalone page fixture."""
    from tests.postgresql.shell_browser import _APP

    seed_organization(authorized)
    screen = _APP.replace('render_application(workspace)', "st.session_state.setdefault('app_sidebar_nav', 'Dashboard')\nrender_application(workspace)")
    with native_server(authorized, tmp_path, screen) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width':1500, 'height':1100})
            page.goto(server.origin)
            frame = page.locator('.st-key-organization_service_frame')
            expect(frame).to_be_visible(timeout=30000)
            assert 0 <= frame.bounding_box()['y'] <= 4
            controls = [page.locator('.st-key-dashboard_filter_status').get_by_role('button'),
                        page.locator('.st-key-dashboard_filter_pool').get_by_role('button'),
                        page.get_by_role('button', name='Advanced filters'),
                        page.get_by_role('button', name='Reset filters')]
            bounds = [control.bounding_box() for control in controls]
            assert len({box['y'] for box in bounds}) == 1
            assert [box['x'] for box in bounds] == sorted(box['x'] for box in bounds)
            managers = page.locator('details').filter(has=page.get_by_text('Project managers', exact=True))
            manager_bounds = managers.bounding_box()
            assert bounds[0]['y'] - (manager_bounds['y'] + manager_bounds['height']) == 8
            matching = page.locator('.st-key-dashboard_project_list details')
            assert matching.bounding_box()['height'] == manager_bounds['height'] == 24
            red, transparent = 'rgb(196, 16, 57)', 'rgba(0, 0, 0, 0)'
            expect(controls[0]).to_have_css('background-color', red)
            expect(controls[1]).to_have_css('background-color', transparent)
            expect(controls[2]).to_have_css('background-color', transparent)
            expect(controls[3]).to_have_css('background-color', transparent)
            status = page.locator('.st-key-dashboard_filter_status')
            expect(status).to_contain_text('In Progress')
            expect(status.locator('[data-testid="stMultiSelectTag"]')).to_have_count(0)
            status.get_by_role('button').click()
            completed = page.get_by_role('checkbox', name='Completed', exact=True)
            expect(page.get_by_role('checkbox', name='In Progress', exact=True)).to_be_checked()
            page.get_by_test_id('stPopoverBody').get_by_text('Completed', exact=True).click()
            expect(page.get_by_text('4 matching projects', exact=True)).to_be_visible()
            expect(controls[0]).to_have_css('background-color', transparent)
            expect(controls[3]).to_have_css('background-color', red)
            expect(completed).to_be_visible()
            page.get_by_role('textbox', name='Search', exact=True).fill('completed')
            page.get_by_role('textbox', name='Search', exact=True).press('Enter')
            expect(page.get_by_role('checkbox', name='In Progress', exact=True)).to_have_count(0)
            expect(completed).to_be_checked()
            page.get_by_role('button', name='Clear', exact=True).click()
            expect(completed).not_to_be_checked()
            expect(controls[0]).to_have_css('background-color', transparent)
            expect(controls[3]).to_have_css('background-color', red)
            page.keyboard.press('Escape')
            controls[3].click()
            expect(controls[3]).to_have_css('background-color', transparent)
            service_a = page.locator('.st-key-dashboard_filter_service_buttons').get_by_role('button', name='Service A', exact=True)
            service_a.click()
            expect(controls[3]).to_have_css('background-color', red)
            service_a.click()
            expect(controls[3]).to_have_css('background-color', transparent)
            status.get_by_role('button').click()
            page.get_by_role('button', name='Select all', exact=True).click()
            expect(completed).to_be_checked()
            page.keyboard.press('Escape')
            page.locator('.st-key-dashboard_clear button').click()
            expect(status).to_contain_text('In Progress')
            expect(page.get_by_text('3 matching projects', exact=True)).to_be_visible()
            expect(controls[0]).to_have_css('background-color', red)
            expect(controls[3]).to_have_css('background-color', transparent)
            page.screenshot(path=str(tmp_path / 'dashboard-compact-shell.png'), full_page=True)
        finally:
            browser.close()
