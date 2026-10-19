"""Current portfolio editing is opt-in and comparison edits only alternatives."""

from copy import deepcopy
import re

import psycopg
import pytest

from tests.postgresql.browser import native_server
from tests.postgresql.test_project_dependency_browser import _APP
from tests.postgresql.test_project_plans import service, draft_task
from app.infrastructure.postgresql.plan_rows import read_plans

api = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = api.expect, api.sync_playwright


def drag(page, bar):
    box = None
    for _ in range(4):
        expect(bar).to_be_visible()
        box = bar.bounding_box()
        if box is not None:
            break
        page.wait_for_timeout(16)  # Mode/rerun reconciliation replaces a virtual row.
    assert box is not None
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 76, y, steps=8)
    page.mouse.up()


def scenario_menu(frame):
    frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
    frame.get_by_role('menuitem', name=re.compile('^Scenario management')).hover()


def display_alternative(page, frame, name='Option A'):
    scenario_menu(frame)
    frame.get_by_text('Display an alternative scenario', exact=True).click()
    page.get_by_role('combobox', name='Alternative scenario', exact=True).click()
    page.get_by_role('option', name=re.compile(name)).click()
    page.get_by_role('button', name='Display scenario', exact=True).click()
    expect(frame.locator('.planning-bar[data-lane=alternative]:not(.planning-milestone)').first).to_be_visible()


def test_create_named_draft_opens_light_blue_comparison_and_copies_allocations(authorized, tmp_path):
    plans = service(authorized, 4)
    initial = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='In Progress'")
        connection.execute("INSERT INTO eppm.project_task(project_id,project_plan_id,task_name,start_date,end_date,progress_pct) VALUES(1,%s,'Build','2027-01-01','2027-01-05',35)", (initial.id,))
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Pool',2)")
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(2,'Container',0)")
        connection.execute('UPDATE eppm.resource_pool SET parent_pool_id=2 WHERE id=1')
        connection.execute('''INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,project_plan_id,fte_assigned)
            VALUES(1,1,1,%s,0.5)''', (initial.id,))
    initial = next(row for row in plans.list_plans(1) if row.is_current)
    with native_server(authorized, tmp_path, _APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width':1700, 'height':1200})
            page.goto(server.origin)
            frame = page.frame_locator('iframe[title*="interactive_gantt"]')
            edit = frame.get_by_role('checkbox', name=re.compile('Enable edit mode'))
            expect(edit).not_to_be_checked(timeout=40000)
            scenario_menu(frame)
            expect(frame.get_by_role('menuitem', name='Create alternative scenario', exact=True)).to_be_hidden()
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click()
            edit.check()
            scenario_menu(frame)
            frame.get_by_text('Create alternative scenario', exact=True).click()
            name = page.get_by_role('textbox', name='Scenario name', exact=True)
            expect(name).to_be_visible()
            page.get_by_role('button', name='Create scenario', exact=True).click()
            expect(page.get_by_text('Plan name is required.', exact=True)).to_be_visible()
            name.fill('  Resource option  ')
            page.get_by_role('button', name='Create scenario', exact=True).click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            frame.locator('[data-control=expandAll]').click()
            bar = frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="1"]) .planning-bar[data-lane=alternative]:not(.planning-milestone)')
            expect(bar).to_be_visible()
            active_count = frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"] .planning-count:not(.planning-comparison-count)').bounding_box()
            alternative_count = frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"] .planning-comparison-count').bounding_box()
            assert alternative_count['y'] >= active_count['y'] + active_count['height']
            alternative_rows = frame.locator('[data-part=resource-left-canvas] .planning-resource-comparison')
            expect(alternative_rows).to_have_count(0)
            assert bar.evaluate('(el)=>getComputedStyle(el).backgroundColor') == 'rgb(125, 211, 252)'
            assert frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="1"]').evaluate('(el)=>getComputedStyle(el).backgroundColor') == 'rgb(224, 242, 254)'
            expect(edit).to_be_checked()
            expect(page.get_by_role('button', name='Close alternative view', exact=True)).to_be_visible()
            with psycopg.connect(authorized.setup.operator_url) as connection:
                alternative_id, status, source, active = connection.execute('''SELECT p.id,s.code,p.source_plan_id,p.is_current
                    FROM eppm.project_plan p JOIN eppm.plan_status s ON s.id=p.status_id
                    WHERE p.project_id=1 AND p.name='Resource option' ''').fetchone()
                contents = read_plans(connection, [initial.id, alternative_id])
                count = connection.execute('SELECT count(*) FROM eppm.project_plan WHERE project_id=1').fetchone()[0]
            assert (status, source, active, count) == ('draft', initial.id, False, 2)
            assert contents[initial.id] == contents[alternative_id] == initial.content
            page.mouse.move(10, 700)
            page.screenshot(path=str(tmp_path / 'created-alternative.png'), full_page=True)
            page.get_by_role('button', name='Close alternative view', exact=True).click()
            expect(frame.locator('.planning-bar[data-lane=alternative]:not(.planning-milestone)')).to_have_count(0)
            display_alternative(page, frame, 'Resource option')
            expect(bar).to_have_css('background-color', 'rgb(147, 51, 234)')
            expect(bar.locator('div').first).to_have_css('background-color', 'rgb(88, 28, 135)')
            expect(frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="1"]')).not_to_have_class(re.compile('planning-new-scenario'))
            page.screenshot(path=str(tmp_path / 'reopened-alternative.png'), full_page=True)
        finally:
            browser.close()


def test_opt_in_editing_and_alternative_lanes(authorized, tmp_path):
    plans = service(authorized, 4)
    initial = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='In Progress'")
        connection.execute("INSERT INTO eppm.project_task(project_id,project_plan_id,task_name,start_date,end_date) VALUES(1,%s,'Build','2027-01-01','2027-01-05'),(1,%s,'Active only','2027-01-07','2027-01-09')", (initial.id, initial.id))
    baseline = plans.baseline_current(1)
    initial = next(row for row in plans.list_plans(1) if row.is_current)
    content = deepcopy(initial.content)
    content.tasks = content.tasks[:1] + [draft_task(-1, 'Extra alternative step', '2027-01-10', '2027-01-12')]
    alternative = plans.save(1, initial.id, initial.revision, 'Option A', content)
    extra = alternative.content.tasks[1]['id']
    with native_server(authorized, tmp_path, _APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1700, 'height': 1200})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(server.origin)
            frame = page.frame_locator('iframe[title*="interactive_gantt"]')
            edit = frame.get_by_role('checkbox', name=re.compile('Enable edit mode'))
            expect(edit).not_to_be_checked(timeout=40000)
            frame.locator('[data-mode=Day]').click()
            expect(page.get_by_text('Enable edit mode to reschedule tasks.', exact=False)).to_have_count(0)
            expect(page.get_by_role('button', name='Close alternative view', exact=True)).to_have_count(0)
            active_bar = frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="1"]) .planning-bar[data-lane=current][data-target-kind=tasks]:not(.planning-milestone)')
            expect(active_bar).to_be_visible()
            drag(page, active_bar)
            scenario_menu(frame)
            expect(frame.get_by_role('menuitem', name='Set current project as baseline', exact=True)).to_be_hidden()
            expect(frame.get_by_role('menuitem', name='Delete baseline', exact=True)).to_be_hidden()
            frame.get_by_text('Display an alternative scenario', exact=True).click()
            picker = page.get_by_role('combobox', name='Alternative scenario', exact=True)
            picker.click()
            expect(page.get_by_role('option', name=re.compile('baseline'))).to_have_count(0)
            page.get_by_role('option', name=re.compile('Option A')).click()
            page.get_by_role('button', name='Display scenario', exact=True).click()
            alt_bar = frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="1"]) .planning-bar[data-lane=alternative]:not(.planning-milestone)')
            expect(alt_bar).to_be_visible()
            expect(alt_bar).to_have_css('background-color', 'rgb(147, 51, 234)')
            expect(page.get_by_role('button', name='Close alternative view', exact=True)).to_be_visible()
            expect(frame.locator(f'.planning-frozen-row[data-target-kind=tasks][data-lane=alternative][data-target-id="{extra}"]')).to_contain_text('Extra alternative step')
            assert frame.locator(f'.planning-frozen-row[data-target-kind=tasks][data-lane=alternative][data-target-id="{extra}"] .planning-column-name').evaluate('(el)=>getComputedStyle(el).color') == 'rgb(147, 51, 234)'
            assert alt_bar.bounding_box()['y'] > active_bar.bounding_box()['y'] + active_bar.bounding_box()['height']
            expect(frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="2"]) .planning-bar[data-lane=alternative]:not(.planning-milestone)')).to_have_count(0)
            drag(page, alt_bar)
            edit.check()
            drag(page, active_bar)
            drag(page, alt_bar)
            expect(alt_bar).to_have_attribute('data-schedule-label', 'Option A · 2027-01-03 → 2027-01-07', timeout=15000)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                saved = read_plans(connection, [initial.id, baseline.id, alternative.id])
            assert saved[initial.id] == initial.content
            assert saved[baseline.id] == baseline.content
            assert saved[alternative.id].tasks[0]['start_date'] == '2027-01-03'
            page.screenshot(path=str(tmp_path / 'alternative-lanes.png'), full_page=True)
            scenario_menu(frame)
            frame.get_by_role('menuitem', name='Show baseline', exact=True).click()
            expect(frame.locator('.planning-bar[data-lane=alternative]:not(.planning-milestone)')).to_have_count(0)
            expect(page.get_by_role('button', name='Close alternative view', exact=True)).to_have_count(0)
            expect(frame.locator('.planning-bar[data-lane=baseline]')).not_to_have_count(0)
            scenario_menu(frame)
            page.once('dialog', lambda dialog: dialog.accept())
            frame.get_by_text('Delete baseline', exact=True).click()
            expect(frame.locator('.planning-bar[data-lane=baseline]')).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT id FROM eppm.project_plan WHERE is_baseline').fetchall() == []
            assert not errors
        finally:
            browser.close()


def test_milestones_and_shared_step_and_resource_dialogs_keep_alternative_isolated(authorized, tmp_path):
    plans = service(authorized, 4)
    active = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='In Progress'")
        connection.execute("INSERT INTO eppm.project_task(project_id,project_plan_id,task_name,start_date,end_date,progress_pct) VALUES(1,%s,'Gate','2027-01-01','2027-01-01',35),(1,%s,'Build','2027-01-03','2027-01-05',60)", (active.id, active.id))
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Engineers',2)")
        connection.execute('INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,project_plan_id,fte_assigned) VALUES(1,1,1,%s,0.25)', (active.id,))
    baseline = plans.baseline_current(1)
    active = next(row for row in plans.list_plans(1) if row.is_current)
    content = deepcopy(active.content)
    content.tasks.append(draft_task(-1, 'Extra gate', '2027-01-07', '2027-01-07'))
    content.dependencies = [dict(task_id=2, predecessor_task_id=1, predecessor_project_id=None, link_type='FS', lag_days=2)]
    alternative = plans.save(1, active.id, active.revision, 'Option A', content)
    extra_id = alternative.content.tasks[-1]['id']
    with native_server(authorized, tmp_path, _APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width':1700, 'height':1200})
            page.goto(server.origin)
            frame = page.frame_locator('iframe[title*="interactive_gantt"]')
            expect(frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="1"]) .planning-bar[data-lane=current].planning-milestone')).to_be_visible(timeout=40000)
            scenario_menu(frame)
            frame.get_by_role('menuitem', name='Show baseline', exact=True).click()
            expect(frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="1"]) .planning-bar[data-lane=baseline].planning-milestone')).to_be_visible()
            display_alternative(page, frame)
            milestone = frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="1"]) .planning-bar[data-lane=alternative].planning-milestone')
            expect(milestone).to_be_visible()
            expect(milestone.locator('.planning-handle:not(.planning-handle-progress)')).to_have_count(0)
            expect(frame.locator(f'.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-lane=alternative][data-target-id="{extra_id}"]) .planning-bar[data-lane=alternative].planning-milestone')).to_be_visible()
            frame.locator('[data-control=edit]').check()
            frame.locator('[data-mode=Day]').click()
            extra_milestone = frame.locator(f'.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-lane=alternative][data-target-id="{extra_id}"]) .planning-bar[data-lane=alternative].planning-milestone')
            drag(page, extra_milestone)
            expect(extra_milestone).not_to_have_attribute('data-schedule-label', 'Milestone: Option A · 2027-01-07 → 2027-01-07', timeout=15000)
            expect(extra_milestone).to_have_attribute('data-schedule-label', re.compile(r'Milestone: Option A · (2027-01-\d{2}) → \1'))
            frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="2"]').dblclick()
            expect(frame.locator('.planning-editor [data-field=name]')).to_have_value('Build')
            for field in ('name', 'phase', 'description', 'start', 'end', 'progress'):
                control = frame.locator(f'.planning-editor [data-field={field}]')
                label = control.locator('..')
                label_text = label.inner_text()
                expect(frame.get_by_label(label_text, exact=True)).to_have_attribute('data-field', field)
                label.click()
                expect(control).to_be_focused()
            expect(frame.locator('.planning-editor [data-part=incoming-dependencies]')).to_have_role('group')
            expect(frame.locator('.planning-editor [data-part=incoming-dependencies]')).to_contain_text('Add Predecessor')
            expect(frame.locator('.planning-editor [data-field=progress]')).to_have_value('60')
            expect(frame.locator('.planning-editor [data-field=predecessor]')).to_have_value('{"kind":"task","id":"1","projectId":"1"}')
            expect(frame.locator('.planning-editor [data-field=lagDays]')).to_have_value('2')
            frame.locator('.planning-editor [data-field=end]').fill('2027-01-03')
            frame.locator('.planning-editor button[type=submit]').click()
            expect(frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="2"]) .planning-bar[data-lane=alternative].planning-milestone')).to_be_visible()
            frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="2"]').dblclick()
            frame.locator('.planning-editor [data-field=end]').fill('2027-01-06')
            frame.locator('.planning-editor button[type=submit]').click()
            expect(frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="2"]) .planning-bar[data-lane=alternative].planning-milestone')).to_have_count(0)
            expect(frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="2"]) .planning-bar[data-lane=alternative]:not(.planning-milestone) .planning-handle:not(.planning-handle-progress)')).to_have_count(2)
            frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="1"]').click(button='right')
            frame.locator('[data-command=manage_task_pools], [data-command=manage_project_pools]').click()
            expect(page.get_by_role('dialog')).to_contain_text('Manage Task Resource Pools')
            expect(page.locator('.st-key-rb_assign_task_period_mode')).to_be_visible()
            page.locator('.st-key-rb_assign_task_period_mode label').filter(has=page.get_by_role('radio')).nth(2).click()
            page.locator('.st-key-assign_task_offset input').fill('2')
            page.locator('.st-key-assign_task_duration input').fill('3')
            page.locator('.st-key-ni_assign_task_fte input').fill('0.5')
            page.screenshot(path=str(tmp_path / 'shared-alternative-resources.png'), full_page=True)
            page.locator('.st-key-btn_confirm_assign_task_pool button').click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                changed = read_plans(connection, [alternative.id])[alternative.id]
            added = next(row for row in changed.assignments if row.schedule_anchor)
            assert (added.task_id, added.fte_assigned, added.offset_days, added.duration_days) == (1, 0.5, 2, 3)
            frame.locator('.planning-frozen-row[data-target-kind=tasks][data-target-id="1"]').click(button='right')
            frame.locator('[data-command=manage_task_pools], [data-command=manage_project_pools]').click()
            expect(page.get_by_role('dialog')).to_contain_text('2027-01-03 → 2027-01-05')
            page.locator(f'.st-key-btn_del_assign_task_{added.id} button').filter(visible=True).first.click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
            frame.locator('[data-command=manage_task_pools], [data-command=manage_project_pools]').click()
            expect(page.get_by_role('dialog')).to_contain_text('Manage Project Resource Pools')
            page.locator('.st-key-ni_assign_proj_fte input').fill('0.7')
            page.locator('.st-key-btn_confirm_assign_proj_pool button').click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                changed = read_plans(connection, [alternative.id])[alternative.id]
                unchanged = read_plans(connection, [active.id, baseline.id])
            assert [row.fte_assigned for row in changed.assignments if row.task_id is None] == [0.7]
            assert [row.fte_assigned for row in changed.assignments if row.task_id == 1] == [0.25]
            assert changed.dependencies == alternative.content.dependencies
            assert changed.tasks[1]['progress_pct'] == 60
            assert unchanged[active.id] == active.content
            assert unchanged[baseline.id] == baseline.content
        finally:
            browser.close()


def test_alternative_context_edits_dependencies_hide_reload_and_confirm_activation(authorized, tmp_path):
    from app.application.services.collaboration import CollaborationService
    from tests.postgresql.test_collaboration import gateway

    CollaborationService(gateway(authorized)).save_catalog('event_type', 'General information')
    plans = service(authorized, 4)
    initial = plans.initialize(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='In Progress'")
        connection.execute("INSERT INTO eppm.project_task(project_id,project_plan_id,task_name,start_date,end_date) VALUES(1,%s,'Build','2027-01-01','2027-01-05')", (initial.id,))
    initial = next(row for row in plans.list_plans(1) if row.is_current)
    content = deepcopy(initial.content)
    content.tasks.append(draft_task(-1, 'Extra step', '2027-01-10', '2027-01-12'))
    content.dependencies = [dict(task_id=-1, predecessor_task_id=1, predecessor_project_id=None, link_type='FS', lag_days=10)]
    alternative = plans.save(1, initial.id, initial.revision, 'Option A', content)
    plans.change(1, alternative.id, alternative.revision, 'status', 'approved')
    extra = alternative.content.tasks[1]['id']
    with native_server(authorized, tmp_path, _APP) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width':1700, 'height':1200})
            page.goto(server.origin)
            frame = page.frame_locator('iframe[title*="interactive_gantt"]')
            edit = frame.get_by_role('checkbox', name=re.compile('Enable edit mode'))
            expect(edit).not_to_be_checked(timeout=40000)
            display_alternative(page, frame)
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
            expect(frame.get_by_role('menuitem', name='Log event', exact=True)).to_be_visible()
            frame.get_by_role('menuitem', name='Log event', exact=True).click()
            expect(page.get_by_role('dialog')).to_be_visible()
            page.get_by_role('dialog').get_by_role('button', name='Cancel', exact=True).click()
            frame.locator('[data-control=internalLinks]').check()
            expect(frame.locator('.planning-link[data-lane=alternative]')).to_have_count(1)
            expect(frame.locator('.planning-link[data-lane=alternative]')).to_have_css('stroke', 'rgb(239, 68, 68)')
            frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="1"]) .planning-bar[data-lane=current][data-target-kind=tasks]:not(.planning-milestone)').click(button='right')
            expect(frame.get_by_role('menuitem', name='Constraint diagnostics', exact=True)).to_be_hidden()
            frame.locator('.planning-timeline-row[data-project-id="1"].planning-project-row .planning-bar[data-lane=current][data-target-kind=projects]').click(button='right')
            expect(frame.get_by_role('menuitem', name='Constraint diagnostics', exact=True)).to_be_hidden()
            frame.locator('[data-part=timeline-header]').click()
            frame.locator('.planning-timeline-row[data-project-id="1"].planning-project-row .planning-bar[data-lane=alternative][data-target-kind=projects]').click(button='right')
            expect(frame.get_by_role('menuitem', name='Constraint diagnostics', exact=True)).to_be_visible()
            frame.locator('[data-mode=Day]').click()
            counts = frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]')
            expect(counts.locator('.planning-count:not(.planning-comparison-count)')).to_have_text('1')
            expect(counts.locator('.planning-comparison-count')).to_contain_text('2')
            counts.locator('.planning-comparison-count').click()
            expect(frame.locator('[data-part=constraint-diagnostics]')).to_contain_text('Extra step')
            expect(frame.locator('[data-part=constraint-diagnostics]')).to_contain_text('2027-01-15')
            frame.locator('[data-part=constraint-diagnostics] [data-close-diagnostics]').click()
            frame.locator(f'.planning-frozen-row[data-target-kind=tasks][data-lane=alternative][data-target-id="{extra}"] .planning-diagnostic-mark').click()
            expect(frame.locator('[data-part=constraint-diagnostics]')).to_be_visible()
            expect(frame.locator('[data-part=constraint-diagnostics]')).to_contain_text('2027-01-15')
            frame.locator('[data-part=constraint-diagnostics] [data-close-diagnostics]').click()
            frame.locator('.planning-link[data-lane=alternative]').dispatch_event('contextmenu', {'clientX':600, 'clientY':300})
            expect(frame.locator('[data-part=dependency-inspector]')).to_contain_text('predecessor')
            expect(frame.locator('[data-part=dependency-inspector]')).to_contain_text('Build')
            expect(frame.locator('[data-part=dependency-inspector]')).to_contain_text('Violated')
            expect(frame.locator('[data-part=dependency-inspector]')).to_contain_text('2027-01-15')
            page.screenshot(path=str(tmp_path / 'shared-dependency-panel.png'), full_page=True)
            expect(frame.locator('[data-part=dependency-inspector] [data-edit-dependency]')).to_be_hidden()
            frame.locator('[data-mode=Day]').click()
            edit.check()
            frame.locator('.planning-link[data-lane=alternative]').dispatch_event('contextmenu', {'clientX':600, 'clientY':300})
            frame.locator('[data-part=dependency-inspector] [data-edit-dependency]').click()
            expect(frame.locator('.planning-editor [data-field=name]')).to_have_value('Extra step')
            expect(frame.locator('.planning-editor [data-field=predecessor]')).to_have_value('{"kind":"task","id":"1","projectId":"1"}')
            expect(frame.locator('.planning-editor [data-field=lagDays]')).to_have_value('10')
            frame.locator('.planning-editor [data-cancel-editor]').click()
            frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="1"]) .planning-bar[data-lane=alternative]:not(.planning-milestone)').click(button='right')
            for label in ['Edit', 'Add Step', 'Delete Step', 'Manage Tags', 'Assign Resource']:
                expect(frame.get_by_role('menuitem', name=label, exact=True)).to_be_visible()
            frame.get_by_role('menuitem', name='Edit', exact=True).click()
            frame.locator('.planning-editor [data-field=name]').fill('Alternative build')
            frame.locator('.planning-editor button[type=submit]').click()
            expect(frame.locator('.planning-editor')).to_be_hidden()
            expect(frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="1"]) .planning-bar[data-lane=alternative]:not(.planning-milestone)')).to_have_attribute('data-plan-revision', str(alternative.revision + 2))
            frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]').click(button='right')
            frame.get_by_role('menuitem', name='Add step', exact=True).click()
            frame.locator('.planning-editor [data-field=name]').fill('New scenario step')
            frame.locator('.planning-editor button[type=submit]').click()
            expect(frame.locator('.planning-frozen-row[data-lane=alternative] .planning-column-name', has_text='New scenario step')).to_be_visible()
            frame.locator(f'.planning-frozen-row[data-target-kind=tasks][data-lane=alternative][data-target-id="{extra}"]').click(button='right')
            page.once('dialog', lambda dialog: dialog.accept())
            frame.get_by_role('menuitem', name='Delete Step', exact=True).click()
            expect(frame.locator(f'.planning-frozen-row[data-target-kind=tasks][data-lane=alternative][data-target-id="{extra}"]')).to_have_count(0)
            expect(frame.locator('.planning-link[data-lane=alternative]')).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                saved = read_plans(connection, [initial.id, alternative.id])
            assert saved[initial.id] == initial.content
            assert [row['task_name'] for row in saved[alternative.id].tasks] == ['Alternative build', 'New scenario step']
            frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="1"]) .planning-bar[data-lane=alternative]:not(.planning-milestone)').click(button='right')
            frame.get_by_role('menuitem', name='Mark as 100% Complete', exact=True).click()
            expect(frame.locator('.planning-timeline-row:has(.planning-bar[data-target-kind=tasks][data-target-id="1"]) .planning-bar[data-lane=alternative]:not(.planning-milestone) > div').first).to_have_attribute('style', re.compile(r'width:\s*100%'))
            with psycopg.connect(authorized.setup.operator_url) as connection:
                saved = read_plans(connection, [initial.id, alternative.id])
            assert saved[initial.id].tasks[0]['progress_pct'] == 0
            assert saved[alternative.id].tasks[0]['progress_pct'] == 100
            scenario_menu(frame)
            frame.get_by_role('menuitem', name='Hide alternative scenarios', exact=True).click()
            expect(frame.locator('.planning-bar[data-lane=alternative]:not(.planning-milestone)')).to_have_count(0)
            close = page.get_by_role('button', name='Close alternative view', exact=True)
            expect(close).to_have_count(0)
            display_alternative(page, frame)
            expect(close).to_be_visible()
            clear = page.locator('.st-key-dashboard_clear button')
            clear_box, close_box = clear.bounding_box(), close.bounding_box()
            assert close_box['width'] >= clear_box['width']
            assert clear_box['y'] + clear_box['height'] <= close_box['y']
            page.screenshot(path=str(tmp_path / 'alternative-toolbar.png'), full_page=True)
            close.click()
            expect(frame.locator('.planning-bar[data-lane=alternative]:not(.planning-milestone)')).to_have_count(0)
            expect(close).to_have_count(0)
            expect(frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]')).to_be_visible()
            expect(edit).to_be_checked()
            display_alternative(page, frame)
            page.reload()
            expect(frame.locator('.planning-frozen-row[data-target-kind=projects][data-target-id="1"]')).to_be_visible(timeout=40000)
            expect(frame.locator('.planning-bar[data-lane=alternative]:not(.planning-milestone)')).to_have_count(0)
            expect(edit).not_to_be_checked()
            display_alternative(page, frame)
            edit.check()
            scenario_menu(frame)
            confirmations = []
            def dismiss(dialog):
                confirmations.append(dialog.message)
                dialog.dismiss()
            page.once('dialog', dismiss)
            frame.get_by_role('menuitem', name='Set alternative as active scenario', exact=True).click()
            assert 'current active plan will become inactive' in confirmations[0]
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current').fetchone()[0] == initial.id
            page.once('dialog', lambda dialog: dialog.accept())
            frame.get_by_role('menuitem', name='Set alternative as active scenario', exact=True).click()
            expect(frame.locator('.planning-bar[data-lane=alternative]:not(.planning-milestone)')).to_have_count(0)
            expect(frame.locator('.planning-column-name', has_text='Alternative build')).to_be_visible()
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current').fetchone()[0] == alternative.id
            expect(page.get_by_test_id('stException')).to_have_count(0)
        finally:
            browser.close()


def test_direct_task_link_in_alternative_persists_without_changing_live_tasks(authorized, tmp_path) -> None:
    """Authenticated alternative linking targets stable task IDs and the selected revision."""
    plans = service(authorized, 4)
    current = plans.initialize(1)
    content = deepcopy(current.content)
    content.tasks = [draft_task(-1, 'Source', '2027-01-01', '2027-01-05'),
                     draft_task(-2, 'Target', '2027-01-10', '2027-01-20')]
    alternative = plans.save(1, current.id, current.revision, 'Link option', content)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='In Progress'")
    with native_server(authorized, tmp_path, _APP, user_id=4) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1700, 'height': 1200})
            page.goto(server.origin)
            frame = page.frame_locator('iframe[title*="interactive_gantt"]')
            frame.get_by_role('checkbox', name=re.compile('Enable edit mode')).check(timeout=40000)
            display_alternative(page, frame, 'Link option')
            bars = frame.locator('.planning-bar[data-lane=alternative][data-target-kind=tasks]')
            expect(bars).to_have_count(2)
            source, target = bars.nth(0).locator('[data-connect=F]'), bars.nth(1).locator('[data-connect=S]')
            source.focus()
            source.press('Enter')
            target.press('Enter')
            expect(frame.locator('.planning-connection-preview')).to_be_hidden(timeout=20000)
            # Rerendered plan diagnostics become inspectable after the authoritative update.
            expect(frame.locator('.planning-link')).to_be_attached(timeout=20000)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                saved = read_plans(connection, [alternative.id])[alternative.id]
            assert len(saved.dependencies) == 1
            assert saved.dependencies[0]['lag_days'] == 0
            assert saved.dependencies[0]['link_type'] == 'FS'
            assert authorized.query('SELECT * FROM eppm.current_task_dependencies') == []
            assert authorized.query('SELECT * FROM eppm.current_project_task') == []
        finally:
            browser.close()
