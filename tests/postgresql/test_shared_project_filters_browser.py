"""The same filter panel scopes dashboard, project grid, and Gantt after navigation."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import re
from typing import TYPE_CHECKING

import psycopg
import pytest

from tests.postgresql.browser import native_server
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.dashboard_browser import _SCREEN
from tests.test_dialog_browser import expect, sync_playwright


_APP = _SCREEN[:_SCREEN.index("if st.session_state.get('nav_redirect'):")] + '''
from app.main import create_project_workspace, create_planning_workspace
from app.presentation.pages.portfolio import render_portfolio_overview
from app.presentation.pages.planning import render_planning_milestones
access = BusinessAccess(actor, authentication.policy)
view = st.radio('View', ['Dashboard', 'Projects', 'Planning', 'Other'], horizontal=True)
if view == 'Dashboard':
    render_dashboard(service)
elif view == 'Projects':
    render_portfolio_overview(create_project_workspace(resources, access=access))
elif view == 'Planning':
    render_planning_milestones(create_planning_workspace(resources, access=access))
'''


if TYPE_CHECKING:
    from playwright.sync_api import Page


_FRAME_RUN_PREFIX = 'Filter test run: '
_VIEW_RUN_PREFIX = 'View test run: '


@contextmanager
def _completed_filter_run(
    page: 'Page', prefix: str = _FRAME_RUN_PREFIX,
) -> Iterator[None]:
    """Observe persistent server completion around one native filter action.

    Args:
        page: Test screen with persistent completion counters.
        prefix: Marker for the filter fragment or page-level navigation.

    Yields:
        Control to perform one expander, filter or navigation action.

    Raises:
        TimeoutError: The requested fragment/page does not finish in 30 seconds.
    """
    marker = page.get_by_test_id('stCaptionContainer').filter(
        has_text=re.compile('^' + re.escape(prefix)),
    )
    previous = int(marker.text_content().strip().removeprefix(prefix))
    yield
    page.wait_for_function("""({previous, prefix}) =>
        [...document.querySelectorAll('[data-testid="stCaptionContainer"]')]
            .some(node => {
                const text = node.textContent.trim();
                return text.startsWith(prefix)
                    && Number(text.slice(prefix.length)) > previous;
            })
    """, arg={'previous': previous, 'prefix': prefix}, timeout=30000)


def _acknowledged_screen(*, filter_marker: bool = True) -> str:
    """Build the native test screen with persistent completion signals."""
    screen = _APP + (
        f"\nst.caption({_VIEW_RUN_PREFIX!r} + "
        "str(st.session_state['shell_runs']))\n"
    )
    if not filter_marker:
        return screen
    screen = """
import streamlit as st
import app.presentation.components.project_filter_panel as panel_module
if not hasattr(panel_module, '_eppm_test_original_panel'):
    panel_module._eppm_test_original_panel = (
        panel_module.organization_filter_panel
    )
    def acknowledged_panel(
        *args: object, **kwargs: object,
    ) -> dict[str, list[str]]:
        '''Emit a test-only fragment completion marker.'''
        result = panel_module._eppm_test_original_panel(*args, **kwargs)
        st.session_state['filter_test_runs'] = (
            st.session_state.get('filter_test_runs', 0) + 1
        )
        st.html(
            '<style>.st-key-eppm_test_filter_completion'
            '{display:none !important}</style>'
        )
        with st.container(key='eppm_test_filter_completion'):
            st.caption(
                'Filter test run: ' + str(st.session_state['filter_test_runs'])
            )
        return result
    panel_module.organization_filter_panel = acknowledged_panel
""" + screen
    return screen


@pytest.mark.parametrize(
    'delayed_frame', [False, True], ids=['immediate', 'delayed'],
)
def test_organization_frames_preserve_state_and_highlight_collapsed_filters(
    authorized: AuthorizedFixture, tmp_path: Path, delayed_frame: bool,
) -> None:
    """Retain completed organization choices across view replacement."""
    screen = _acknowledged_screen()
    if delayed_frame:
        screen = """
import time
import streamlit as st
from streamlit.elements.lib.mutable_expander_container import (
    ExpanderContainer,
)
if not hasattr(st, '_eppm_test_original_expander'):
    st._eppm_test_original_expander = st.expander
    def delayed_expander(
        *args: object, **kwargs: object,
    ) -> ExpanderContainer:
        '''Delay only the test-owned Teams expander return.'''
        frame = st._eppm_test_original_expander(*args, **kwargs)
        if kwargs.get('key') == 'organization_frame_org_team':
            time.sleep(0.5)
        return frame
    st.expander = delayed_expander
""" + screen
    with (
        native_server(authorized, tmp_path, screen) as server,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1600, 'height': 1200})
            page.goto(server.origin)
            for facet in ('division', 'org_team', 'org_manager'):
                frame = page.locator('.st-key-organization_frame_' + facet)
                expect(frame.locator('summary')).to_be_visible(timeout=30000)
                with _completed_filter_run(page):
                    frame.locator('summary').click()
                with _completed_filter_run(page):
                    frame.get_by_role('button').first.click()
                with _completed_filter_run(page):
                    frame.locator('summary').click()
                expect(frame.locator('summary')).to_have_css(
                    'background-color', 'rgb(196, 16, 57)',
                )
            team = page.locator('.st-key-organization_frame_org_team')
            with _completed_filter_run(page):
                team.locator('summary').click()
            for view in ('Other', 'Projects', 'Planning', 'Dashboard'):
                with _completed_filter_run(page, _VIEW_RUN_PREFIX):
                    page.get_by_test_id('stRadio').get_by_text(
                        view, exact=True,
                    ).click()
                if view == 'Other':
                    expect(team).to_have_count(0)
                    continue
                expect(team.locator('details')).to_have_attribute('open', '')
                for facet in ('division', 'org_manager'):
                    summary = page.locator(
                        '.st-key-organization_frame_' + facet + ' summary'
                    )
                    expect(summary).to_have_css(
                        'background-color', 'rgb(196, 16, 57)',
                    )
                expect(page.get_by_test_id('stException')).to_have_count(0)
            page.screenshot(
                path=str(Path('.local/organization-frame-state.png').resolve()),
            )
        finally:
            browser.close()


def test_shared_status_filter_survives_navigation_and_widget_cleanup(
    authorized: AuthorizedFixture, tmp_path: Path,
) -> None:
    """Preserve status selection and layout after completed navigation."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='Project '||id, status=CASE id WHEN 1 THEN 'Completed' ELSE 'In Progress' END")
        connection.execute("INSERT INTO eppm.project_task(project_id,project_plan_id,task_name,start_date,end_date) SELECT id,(SELECT id FROM eppm.project_plan WHERE project_id=p.id AND is_current),'Task '||id,'2026-01-01','2026-02-01' FROM eppm.project p")
    with native_server(
        authorized, tmp_path, _acknowledged_screen(filter_marker=False),
    ) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1600, 'height': 1200})
            page.goto(server.origin)
            status = page.locator('.st-key-dashboard_filter_status').last
            expect(status).to_contain_text('In Progress', timeout=30000)
            status.get_by_role('button').click()
            page.locator('.st-key-dashboard_filter_status_option_Completed label').click()
            expect(status).to_contain_text('Completed')
            page.locator('[class*="st-key-dashboard_filter_status_option_In"] label').click()
            expect(status).not_to_contain_text('In Progress')
            page.keyboard.press('Escape')
            for view in ('Other', 'Projects', 'Planning', 'Dashboard'):
                with _completed_filter_run(page, _VIEW_RUN_PREFIX):
                    page.get_by_test_id('stRadio').get_by_text(view, exact=True).click()
                if view == 'Other':
                    expect(status).to_have_count(0)
                    continue
                if view == 'Dashboard':
                    expect(page.locator('.st-key-dashboard_finance_chart')).to_be_visible()
                expect(status).to_contain_text('Completed')
                expect(status).not_to_contain_text('In Progress')
                if view == 'Projects':
                    rows = page.locator('.st-key-portfolio_master_table tbody tr[data-project-id]')
                    expect(rows).to_have_count(1)
                    expect(rows.first).to_have_attribute('data-project-id', '1')
                if view == 'Planning':
                    project_button = page.locator('.st-key-planning_project_filter_slot button')
                    project_box = project_button.bounding_box()
                    status_box = status.get_by_role('button').bounding_box()
                    assert abs(project_box['y'] - status_box['y']) < 1
                    assert project_box['x'] < status_box['x']
                    page.locator('.st-key-planning_project_filter_slot button').click()
                    selection = page.locator('.st-key-ms_multi_projects')
                    expect(selection).to_contain_text('1 projects found')
                    page.keyboard.press('Escape')
                    expect(page.locator('iframe[title*="interactive_gantt"]')).to_be_visible(timeout=30000)
                    expect(page.locator('.st-key-portfolio_master_table')).to_have_count(0)
                manager_box = page.locator('.st-key-organization_filter_frames details').last.bounding_box()
                status_box = status.get_by_role('button').bounding_box()
                reset_box = page.locator('.st-key-dashboard_clear button').bounding_box()
                assert abs(status_box['height'] - manager_box['height']) < 1
                assert abs(reset_box['height'] - manager_box['height']) < 1
                assert abs(status_box['y'] - manager_box['y'] - manager_box['height'] - 8) < 1
                assert float(page.get_by_test_id('stMainBlockContainer').evaluate(
                    'node => parseFloat(getComputedStyle(node).paddingTop)')) < 1
                if view == 'Projects':
                    create_box = page.locator('.st-key-btn_create_project_from_portfolio button').bounding_box()
                    assert abs(create_box['x'] + create_box['width'] - reset_box['x'] - reset_box['width']) < 1
                page.screenshot(path=str(Path(f'.local/shared-filters-{view.lower()}.png').resolve()), full_page=True)
                expect(page.get_by_test_id('stException')).to_have_count(0)
            page.locator('.st-key-dashboard_clear button').click()
            expect(status).to_contain_text('In Progress')
            with _completed_filter_run(page, _VIEW_RUN_PREFIX):
                page.get_by_test_id('stRadio').get_by_text(
                    'Projects', exact=True,
                ).click()
            expect(status).to_contain_text('In Progress')
            expect(page.locator('.st-key-portfolio_master_table tbody tr[data-project-id="1"]')).to_have_count(0)
        finally:
            browser.close()
