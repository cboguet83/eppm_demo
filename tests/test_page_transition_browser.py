"""Verify immediate blanking and completed-page reveal in a real browser."""

import pytest

from tests.test_dialog_browser import popup_server, sync_playwright, expect
from tests.postgresql.browser_completion import ScriptCompletion


_APP = '''
import time
import streamlit as st
from app.presentation.shell import render_application
from app.presentation.components.application_workspace import ApplicationWorkspace
from app.presentation.navigation import PAGE_PORTFOLIO, PAGE_PLANNING

def slow():
    st.write('First destination content')
    time.sleep(1)
    st.write('Destination ready')

render_application(ApplicationWorkspace('transition-test', {
    PAGE_PORTFOLIO: lambda: st.write('Original page'),
    PAGE_PLANNING: slow,
}, None))
'''


@pytest.mark.parametrize('popup_server', [_APP], indirect=True)
@pytest.mark.parametrize('coalesced_state', [False, True])
def test_navigation_blanks_old_page_until_destination_ready(
    popup_server: str, coalesced_state: bool,
) -> None:
    """Keep every unfinished frame blank, including coalesced run states."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            completion = ScriptCompletion(page)
            page.goto(popup_server)
            expect(page.get_by_text('Original page', exact=True)).to_be_visible()
            page.wait_for_selector('#eppm-page-transition', state='attached')
            page.evaluate('''() => {
                window.unfinishedVisibleFrames = [];
                document.addEventListener('click', () => {
                    const sample = () => {
                        const main = document.querySelector('[data-testid="stMain"]');
                        if (main.textContent.includes('Destination ready')) return;
                        if (getComputedStyle(main).visibility !== 'hidden') {
                            window.unfinishedVisibleFrames.push(main.textContent);
                        }
                        requestAnimationFrame(sample);
                    };
                    requestAnimationFrame(sample);
                }, {once: true, capture: true});
            }''')
            # A real server completion must reveal the destination even when React
            # never exposes the intermediate running state to this component.
            with completion.action():
                if coalesced_state:
                    page.evaluate('''() => {
                        const app = document.querySelector('[data-testid="stApp"]');
                        const getAttribute = app.getAttribute.bind(app);
                        app.getAttribute = name => name === 'data-test-script-state'
                            ? 'notRunning' : getAttribute(name);
                    }''')
                page.get_by_text('Planning & Milestones', exact=True).click()
                expect(page.locator('#eppm-page-transition')).to_be_visible()
                expect(page.locator('[data-testid="stMain"]')).to_be_hidden()

            expect(page.get_by_text('Destination ready', exact=True)).to_be_visible()
            expect(page.locator('#eppm-page-transition')).to_be_hidden()
            expect(page.get_by_text('Original page', exact=True)).to_have_count(0)
            assert page.evaluate('window.unfinishedVisibleFrames') == []
        finally:
            browser.close()


_CHART_APP = _APP.replace("render_application(ApplicationWorkspace", '''
from datetime import date
from app.presentation.components.dashboard_resource_chart import resource_chart

@st.fragment
def chart_page():
    series = {'allocation': {'2026-Q1': 2}, 'capacity': {'2026-Q1': 1},
              'pools': [{'pool_id': 1, 'name': 'Pool A', 'allocation': {'2026-Q1': 2},
                         'overallocation': {'2026-Q1': 1}, 'available': {'2026-Q1': -1}}]}
    labels = {'title': 'Allocation', 'goTo': 'Open planning', 'poolDetails': 'Pool details',
              'filterPool': 'Filter on this pool', 'valueLabel': 'Allocation'}
    event = resource_chart(series, today='2026-01-01', year=2026, labels=labels,
                           locale='en', metric='allocation')
    if event and event['action'] == 'planning':
        time.sleep(.5)
        st.session_state['nav_redirect'] = PAGE_PLANNING
        st.rerun()
    if event and event['action'] == 'pool_details':
        time.sleep(.5)
        st.info('No accessible destination')

render_application(ApplicationWorkspace''').replace("lambda: st.write('Original page')", 'chart_page')


@pytest.mark.parametrize('popup_server', [_CHART_APP], indirect=True)
@pytest.mark.parametrize('destination', ['Open planning', 'Pool details'])
def test_chart_navigation_shows_loading_and_clears_it_after_completion(popup_server, destination):
    """Cover full rerun handoff and a navigation request with no destination."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(popup_server)
            bar = page.locator('.resource-chart rect[data-pool-id="1"]')
            expect(bar).to_be_visible(timeout=30000)
            bar.click(button='right')
            page.get_by_role('menuitem', name=destination, exact=True).click()
            expect(page.locator('#eppm-page-transition')).to_be_visible()
            expect(page.get_by_test_id('stMain')).to_be_hidden()
            ready = 'Destination ready' if destination == 'Open planning' else 'No accessible destination'
            expect(page.get_by_text(ready, exact=True)).to_be_visible()
            expect(page.locator('#eppm-page-transition')).to_be_hidden()
        finally:
            browser.close()
