"""Real Gantt dependency panel saves through the restricted PostgreSQL service."""

import psycopg
import pytest
import re

from tests.postgresql.browser import native_server
from tests.postgresql.test_project_dependencies import links as links

_playwright = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = _playwright.expect, _playwright.sync_playwright

_APP = '''
import streamlit as st
from app.application.services.business_access import BusinessAccess
from app.main import create_planning_workspace
from app.presentation.pages.planning import render_planning_milestones
from app.presentation.i18n import set_current_locale
from app.runtime import process_runtime
from tests.postgresql.browser import browser_access

st.set_page_config(layout='wide')
runtime = process_runtime()
authentication = browser_access(runtime)
actor = authentication.actor(st.context.cookies.get('eppm_session', ''))
access = BusinessAccess(actor, authentication.policy)
set_current_locale('en')
st.session_state.setdefault('ms_multi_projects', [1])
render_planning_milestones(create_planning_workspace(runtime, access=access))
'''


def test_project_menu_panel_saves_cancels_and_retains_stale_drafts_without_step_fields(links, tmp_path):
    with psycopg.connect(links.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='In Progress'")
    with native_server(links, tmp_path, _APP, user_id=1) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1600, 'height': 1200})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(server.origin)
            frame = page.frame_locator('iframe[title*="interactive_gantt"]')
            frame.get_by_role('checkbox', name=re.compile('Enable edit mode')).check(timeout=40000)
            label = frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]')
            label.click(button='right', timeout=40000)
            frame.get_by_role('menuitem', name='Manage dependencies', exact=True).click()
            expect(frame.locator('[data-part=project-dependency-editor] h3')).to_have_text('Manage dependencies — Editable')
            expect(frame.locator('[data-part=project-dependency-editor] button:has-text("Add predecessor")')).to_be_enabled(timeout=15000)
            for field in ['task-name', 'task-phase', 'task-desc', 'start-date', 'end-date', 'progress']:
                expect(frame.locator('[data-part=project-dependency-editor] [data-field=' + {'task-name':'name','task-phase':'phase','task-desc':'description','start-date':'start','end-date':'end','progress':'progress'}[field] + ']')).to_be_hidden()
            frame.locator('[data-part=project-dependency-editor] button:has-text("Add predecessor")').click()
            target = frame.locator('[data-part=project-dependency-editor]').get_by_role('combobox', name='Predecessor', exact=True)
            expect(target).to_be_enabled(timeout=15000)
            expect(frame.locator('[data-part=project-dependency-editor] [data-control=crossProject]')).to_be_hidden()
            expect(frame.locator('[data-part=project-dependency-editor] [data-choice-project] option')).to_have_count(1)
            expect(frame.locator('[data-part=project-dependency-editor] [data-field=type]')).to_have_value('FS')
            expect(frame.locator('[data-part=project-dependency-editor] [data-field=lagDays]')).to_have_value('0')
            frame.locator('[data-part=project-dependency-editor] button:has-text("Cancel")').click()
            assert links.query('SELECT * FROM eppm.project_dependency', user_id=4) == []

            # Summary bars expose the same menu and successor, with a whole-project predecessor.
            frame.locator('.planning-bar[data-target-kind=projects][data-lane=current]').click(button='right')
            frame.get_by_role('menuitem', name='Manage dependencies', exact=True).click()
            expect(frame.locator('[data-part=project-dependency-editor] button:has-text("Add predecessor")')).to_be_enabled(timeout=15000)
            frame.locator('[data-part=project-dependency-editor] button:has-text("Add predecessor")').click()
            expect(target).to_be_enabled(timeout=15000)
            frame.locator('[data-part=project-dependency-editor] button[type=submit]').click()
            expect(frame.locator('[data-part=project-dependency-editor]')).to_be_hidden(timeout=15000)
            assert links.query('SELECT project_id,predecessor_project_id,predecessor_task_id FROM eppm.project_dependency', user_id=4) == [(1, 2, None)]
            expect(frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"] [data-diagnostics]')).to_be_visible()
            frame.locator('[data-control=externalLinks]').check()
            expect(frame.locator('[data-part=dependencies] path').first).to_be_attached()

            label.click(button='right')
            frame.get_by_role('menuitem', name='Constraint diagnostics', exact=True).click()
            expect(frame.locator('[data-part=constraint-diagnostics]')).to_contain_text('project start is too early')
            frame.locator('[data-part=constraint-diagnostics]').get_by_role('button', name='Manage dependencies', exact=True).click()
            expect(frame.locator('[data-part=project-dependency-editor] button[type=submit]')).to_be_enabled(timeout=15000)
            expect(target).to_be_enabled(timeout=15000)
            frame.locator('[data-part=project-dependency-editor] [data-field=lagDays]').fill('-2')
            with psycopg.connect(links.setup.operator_url) as c:
                c.execute("UPDATE eppm.project_task SET end_date='2026-01-16' WHERE id=2")
            frame.locator('[data-part=project-dependency-editor] button[type=submit]').click()
            expect(frame.locator('[data-part=project-dependency-editor] [role=alert]')).to_contain_text('changed', timeout=15000)
            expect(frame.locator('[data-part=project-dependency-editor] [data-field=lagDays]')).to_have_value('-2')
            expect(frame.locator('[data-part=project-dependency-editor]')).to_be_visible()
            frame.locator('[data-part=project-dependency-editor] button:has-text("Reload dependencies")').click()
            expect(frame.locator('[data-part=project-dependency-editor] [data-field=lagDays]')).to_have_value('0', timeout=15000)
            expect(target).to_be_enabled(timeout=15000)
            target.select_option('{"kind":"task","id":"2","projectId":"2"}')
            frame.locator('[data-part=project-dependency-editor] [data-field=type]').select_option('SS')
            frame.locator('[data-part=project-dependency-editor] [data-field=lagDays]').fill('-2')
            frame.locator('[data-part=project-dependency-editor] button[type=submit]').click()
            expect(frame.locator('[data-part=project-dependency-editor]')).to_be_hidden(timeout=15000)
            assert links.query('SELECT predecessor_project_id,predecessor_task_id,link_type,lag_days FROM eppm.project_dependency', user_id=4) == [(None, 2, 'SS', -2)]
            assert links.query('SELECT * FROM eppm.task_dependencies', user_id=4) == []

            frame.locator('.planning-bar[data-target-kind=tasks][data-lane=current]').first.click(button='right')
            frame.get_by_role('menuitem', name='Edit', exact=True).click()
            expect(frame.locator('.planning-editor [data-field=name]')).to_be_visible()
            expect(frame.locator('.planning-editor [data-field=name]')).to_have_value('Successor')
            frame.locator('.planning-editor [data-field=name]').fill('Edited successor step')
            frame.locator('.planning-editor button[type=submit]').click()
            expect(frame.locator('.planning-editor')).to_be_hidden(timeout=15000)
            expect(frame.locator('[data-part=timeline-left-canvas]')).to_contain_text('Edited successor step', timeout=15000)
            assert links.query('SELECT task_name FROM eppm.project_task WHERE id=1', user_id=4) == [('Edited successor step',)]
            assert len(links.query('SELECT * FROM eppm.project_dependency', user_id=4)) == 1
            label.click(button='right')
            frame.get_by_role('menuitem', name='Manage dependencies', exact=True).click()
            expect(frame.locator('[data-part=project-dependency-editor] button[type=submit]')).to_be_enabled(timeout=15000)
            frame.locator('[data-part=project-dependency-editor] button:has-text("Remove")').click()
            frame.locator('[data-part=project-dependency-editor] button[type=submit]').click()
            expect(frame.locator('[data-part=project-dependency-editor]')).to_be_hidden(timeout=15000)
            assert links.query('SELECT * FROM eppm.project_dependency', user_id=4) == []
            assert errors == []
            page.screenshot(path=str(tmp_path / 'project-dependencies.png'), full_page=True)
        finally:
            browser.close()
