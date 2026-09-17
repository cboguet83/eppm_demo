"""Browser coverage for creating a child and inspecting a container pool."""

import psycopg
import pytest

from app.domain.resources.models import PoolAssignment, ResourcePool
from tests.postgresql.browser import native_server
from tests.postgresql.test_resource_pools import service

playwright_api = pytest.importorskip('playwright.sync_api')
expect, sync_playwright = playwright_api.expect, playwright_api.sync_playwright

SCREEN = '''
import streamlit as st
from app.application.services.business_access import BusinessAccess
from app.main import create_resource_pool_service, create_pool_capacity_service, create_organization_service
from app.presentation.pages.resource_pools import render_resource_pools
from app.presentation.i18n import set_current_locale
from app.runtime import process_runtime
from tests.postgresql.browser import browser_access
from app.presentation.components.dialog import install_dialog_presentation
st.set_page_config(layout='wide')
install_dialog_presentation()
runtime = process_runtime()
authentication = browser_access(runtime)
actor = authentication.actor(st.context.cookies.get('eppm_session', ''))
access = BusinessAccess(actor, authentication.policy)
set_current_locale('en')
render_resource_pools(create_resource_pool_service(runtime, access=access),
    create_pool_capacity_service(runtime, access=access),
    create_organization_service(runtime, access=access), 'planning')
'''


def test_context_delete_and_undelete_with_deleted_visibility_filter(authorized, tmp_path):
    identity = service(authorized).create_pool(ResourcePool('Restorable', capacity_fte=4))
    with native_server(authorized, tmp_path, SCREEN) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1500, 'height': 1000})
            page.goto(server.origin)
            toggle = page.get_by_role('checkbox', name='Show deleted pools', exact=True)
            expect(toggle).not_to_be_checked(timeout=30000)
            row = page.get_by_role('treeitem', name='Restorable', exact=True)
            row.click(button='right')
            expect(page.get_by_role('menuitem', name='Undelete pool', exact=True)).to_have_count(0)
            page.get_by_role('menuitem', name='Delete pool', exact=True).click()
            page.get_by_role('dialog').get_by_role('button', name='Yes, Delete', exact=True).click()
            expect(row).to_have_count(0)
            page.get_by_text('Show deleted pools', exact=True).click()
            expect(toggle).to_be_checked()
            deleted = page.get_by_role('treeitem', name='Restorable (Deleted)', exact=True)
            expect(deleted).to_be_visible()
            expect(deleted.locator('.pool-deleted')).to_have_text('Deleted')
            expect(deleted.locator('.pool-meta').nth(3)).to_have_text('')
            deleted.click(button='right')
            expect(page.get_by_role('menuitem', name='Delete pool', exact=True)).to_have_count(0)
            expect(page.get_by_role('menuitem', name='Edit pool', exact=True)).to_have_count(0)
            page.screenshot(path=str(tmp_path / 'deleted-pool-menu.png'), full_page=True)
            page.get_by_role('menuitem', name='Undelete pool', exact=True).click()
            expect(row).to_be_visible()
            expect(row.locator('.pool-deleted')).to_have_count(0)
            expect(row.locator('.pool-meta').nth(3)).to_have_text('4.00')
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT deleted_flag FROM eppm.resource_pool WHERE id=%s', (identity,)).fetchone() == (False,)
        finally:
            browser.close()


def test_capacity_excess_colors_values_and_warns_next_to_pool_names(authorized, tmp_path):
    screen = '''
import streamlit as st
from app.domain.resources.hierarchy import PoolHierarchy
from app.domain.resources.models import ResourcePool
from app.presentation.components.resource_pool_tree import resource_pool_tree
st.set_page_config(layout='wide')
tree = PoolHierarchy([ResourcePool('Container', id=1),
    ResourcePool('Current excess', id=2, parent_pool_id=1),
    ResourcePool('Peak excess', id=3, parent_pool_id=1),
    ResourcePool('At capacity', id=4, parent_pool_id=1)])
resource_pool_tree(tree, {1:6, 2:2, 3:2, 4:2}, 1,
    assigned_capacities={1:7, 2:4, 3:1, 4:2},
    peak_demands={1:7, 2:1, 3:4, 4:2})
'''


    with native_server(authorized, tmp_path, screen) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1700, 'height': 900})
            page.goto(server.origin)
            for name, current, peak in [
                ('Container', False, False), ('Current excess', True, False),
                ('Peak excess', False, True), ('At capacity', False, False),
            ]:
                row = page.get_by_role('treeitem', name=name, exact=True)
                expect(row).to_be_visible(timeout=30000)
                expect(row.locator('.pool-name .pool-warning')).to_have_count(int(current or peak))
                for index, exceeded in [(4, current), (6, peak)]:
                    cell = row.locator('.pool-meta').nth(index)
                    if exceeded:
                        expect(cell).to_have_css('color', 'rgb(198, 40, 40)')
                    else:
                        expect(cell).not_to_have_css('color', 'rgb(198, 40, 40)')
            page.screenshot(path=str(tmp_path / 'capacity-warnings.png'), full_page=True)
        finally:
            browser.close()


def test_empty_pool_list_creates_root_from_context_menu_without_toolbar_button(authorized, tmp_path):
    with native_server(authorized, tmp_path, SCREEN) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser)
            page.goto(server.origin)
            empty = page.get_by_text('No pools yet. Right-click here to create a pool.', exact=True)
            expect(empty).to_be_visible(timeout=30000)
            expect(page.get_by_role('button', name='Create Pool', exact=True)).to_have_count(0)
            empty.click(button='right')
            page.get_by_role('menuitem', name='Create pool', exact=True).click()
            dialog = page.get_by_role('dialog')
            dialog.get_by_role('textbox', name='Resource Pool Name *', exact=True).fill('First pool')
            dialog.get_by_role('button', name='Save', exact=True).click()
            expect(dialog).to_have_count(0)
            expect(page.get_by_role('treeitem', name='First pool', exact=True)).to_be_visible()
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT name,parent_pool_id FROM eppm.resource_pool').fetchall() == [('First pool', None)]
        finally:
            browser.close()


def test_create_child_switches_parent_to_container_and_disables_direct_capacity(authorized, tmp_path):
    parent = service(authorized).create_pool(ResourcePool('Engineering', capacity_fte=20))
    with native_server(authorized, tmp_path, SCREEN) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1400, 'height': 1050})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(server.origin)
            tree = page.get_by_role('tree', name='Resource pools')
            parent_row = tree.get_by_role('treeitem', name='Engineering', exact=True)
            expect(parent_row).to_be_visible(timeout=30000)
            expect(page.get_by_role('heading', name='Resource Pools Management', exact=False)).to_have_count(0)
            parent_row.click(button='right')
            page.get_by_role('menuitem', name='Create pool', exact=True).click()
            dialog = page.get_by_role('dialog')
            dialog.get_by_role('textbox', name='Resource Pool Name *', exact=True).fill('Backend')
            dialog.get_by_role('spinbutton', name='Defined capacity (FTE)', exact=True).fill('4')
            dialog.get_by_role('button', name='Save', exact=True).click()
            expect(dialog).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                rows = connection.execute('SELECT name,parent_pool_id,capacity_fte FROM eppm.resource_pool ORDER BY id').fetchall()
                assert rows == [('Engineering', None, 0), ('Backend', parent, 4)]
            expect(page.get_by_text('No overassigned periods for Engineering.', exact=True)).to_be_visible()
            expect(parent_row).to_have_attribute('aria-selected', 'true')
            expect(parent_row.locator('.pool-meta').nth(3)).to_have_text('')
            child_row = tree.get_by_role('treeitem', name='Backend', exact=True)
            expect(child_row).to_have_attribute('aria-level', '2')
            parent_row.press('ArrowLeft')
            expect(child_row).to_have_count(0)
            expect(parent_row).to_be_focused()
            page.keyboard.press('ArrowRight')
            expect(child_row).to_be_visible()
            child_row.click()
            expect(child_row).to_have_attribute('aria-selected', 'true')
            expect(page.get_by_text('No overassigned periods for Backend.', exact=True)).to_be_visible()
            parent_row.click()
            expect(parent_row).to_have_attribute('aria-selected', 'true')
            expect(page.get_by_role('button', name='Edit', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='Delete', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='Create pool', exact=True)).to_have_count(0)
            expect(parent_row).to_have_css('font-weight', '700')
            assert abs(parent_row.bounding_box()['height'] - 36.4) < 1
            expect(tree.get_by_role('button', name='Filter Pool type', exact=True)).to_be_visible()
            expect(tree.get_by_role('button', name='Filter Hierarchy type', exact=True)).to_be_visible()
            expect(tree.get_by_role('button', name='Filter Current Capacity (FTE)', exact=True)).to_be_visible()
            expect(parent_row).to_contain_text('Human')
            expect(tree.get_by_role('button', name='Filter Pool Capacity (FTE)', exact=True)).to_be_visible()
            expect(tree.get_by_role('button', name='Filter Future Peak Demand (FTE)', exact=True)).to_be_visible()
            expect(page.get_by_text('Mapped Capacity Breakdown', exact=True)).to_be_visible()
            expect(page.get_by_text('Active Allocations on Projects & Tasks', exact=True)).to_be_visible()
            expect(parent_row).to_have_css('background-color', 'rgb(241, 243, 245)')
            expect(page.get_by_text('No overassigned periods for Engineering.', exact=True)).to_be_visible()
            page.screenshot(path=str(tmp_path / 'container-pool.png'), full_page=True)
            parent_row.press('Shift+F10')
            page.get_by_role('menuitem', name='Edit pool', exact=True).click()
            expect(dialog.get_by_role('spinbutton', name='Defined capacity (FTE)', exact=True)).to_be_disabled()
            expect(dialog.get_by_role('combobox', name='Parent pool', exact=True)).to_be_visible()
            dialog.get_by_role('textbox', name='Resource Pool Name *', exact=True).fill('Engineering renamed')
            dialog.get_by_role('button', name='Save Changes', exact=True).click()
            expect(dialog).to_have_count(0)
            expect(tree.get_by_role('treeitem', name='Engineering renamed', exact=True).locator('.pool-meta').nth(3)).to_have_text('')
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT capacity_fte FROM eppm.resource_pool WHERE id=%s', (parent,)).fetchone() == (0,)
            assert not errors
        finally:
            browser.close()


def test_context_child_creation_warns_for_assigned_pool(authorized, tmp_path):
    pools = service(authorized)
    parent = pools.create_pool(ResourcePool('Assigned pool', capacity_fte=8))
    pools.create_assignment(PoolAssignment(parent, 1, 1))
    with native_server(authorized, tmp_path, SCREEN) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser)
            page.goto(server.origin)
            row = page.get_by_role('treeitem', name='Assigned pool', exact=True)
            row.click(button='right', timeout=30000)
            page.get_by_role('menuitem', name='Create pool', exact=True).click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            expect(page.get_by_text('Remove or reassign them before adding children.', exact=False).first).to_be_visible()
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT id,capacity_fte FROM eppm.resource_pool').fetchall() == [(parent, 8)]
        finally:
            browser.close()


def test_header_filters_keep_ancestors_and_pool_tags_and_exception_editor_are_visible(authorized, tmp_path):
    pools = service(authorized)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.tag_group(id,tag_group_name) VALUES(1,'pool_tag'),(2,'project_tag')")
        connection.execute("INSERT INTO eppm.tag_dictionnary(id,tag,tag_group_id) VALUES(1,'Backend skill',1),(2,'Project only',2)")
    parent = pools.create_pool(ResourcePool('Engineering', capacity_fte=10))
    child = pools.create_pool(ResourcePool('Backend', capacity_fte=4, parent_pool_id=parent), tag_ids=[1])
    pools.create_pool(ResourcePool('Other', capacity_fte=2, parent_pool_id=parent))
    with native_server(authorized, tmp_path, SCREEN) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1600, 'height': 1100})
            page.goto(server.origin)
            tree = page.get_by_role('tree', name='Resource pools')
            expect(tree).to_be_visible(timeout=30000)
            parent_row = tree.get_by_role('treeitem', name='Engineering', exact=True)
            child_row = tree.get_by_role('treeitem', name='Backend', exact=True)
            expect(child_row).to_contain_text('Backend skill')
            page.get_by_role('button', name='Filter Pool Capacity (FTE)', exact=True).click()
            page.get_by_role('dialog', name='Filter Pool Capacity (FTE)', exact=True).get_by_role('button', name='Sort ascending', exact=True).click()
            expect(tree.get_by_role('treeitem').nth(1)).to_have_attribute('aria-label', 'Other')
            parent_row.press('ArrowLeft')
            expect(child_row).to_have_count(0)
            tag_filter = page.get_by_role('button', name='Filter Tags', exact=True)
            tag_filter.click()
            popup = page.get_by_role('dialog', name='Filter Tags', exact=True)
            popup.get_by_role('checkbox', name='Select all', exact=True).uncheck()
            popup.get_by_role('searchbox', name='Search filter values', exact=True).fill('Backend')
            popup.get_by_role('checkbox', name='Backend skill', exact=True).check()
            popup.get_by_role('button', name='Apply', exact=True).click()
            expect(child_row).to_be_visible()
            expect(parent_row).to_be_visible()
            expect(tree.get_by_role('treeitem', name='Other', exact=True)).to_have_count(0)
            capacity_filter = page.get_by_role('button', name='Filter Pool Capacity (FTE)', exact=True)
            capacity_filter.click()
            popup = page.get_by_role('dialog', name='Filter Pool Capacity (FTE)', exact=True)
            popup.get_by_role('checkbox', name='Select all', exact=True).uncheck()
            popup.get_by_role('button', name='Apply', exact=True).click()
            expect(page.get_by_text('No pools match these filters.', exact=True)).to_be_visible()
            capacity_filter.click()
            page.get_by_role('dialog', name='Filter Pool Capacity (FTE)', exact=True).get_by_role('button', name='Clear filter', exact=True).click()
            expect(child_row).to_be_visible()
            child_row.click(button='right')
            expect(child_row).to_have_attribute('aria-selected', 'true')
            expect(page.get_by_text('No overassigned periods for Backend.', exact=True)).to_be_visible()
            page.get_by_role('menuitem', name='Edit pool', exact=True).click()
            dialog = page.get_by_role('dialog')
            tag_selector = dialog.get_by_role('combobox', name='Pool tags', exact=True)
            tag_selector.click()
            expect(page.get_by_role('option', name='project_tag · Project only', exact=True)).to_have_count(0)
            tag_selector.press('Escape')
            exceptions = dialog.get_by_text('Capacity exceptions', exact=True)
            expect(exceptions).to_be_visible()
            assert exceptions.bounding_box()['y'] > dialog.get_by_role('button', name='Save Changes', exact=True).bounding_box()['y']
            exceptions.click()
            dialog.get_by_role('textbox', name='Reason', exact=True).fill('Training')
            dialog.get_by_role('button', name='Save exception', exact=True).click()
            expect(dialog).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT reason FROM eppm.resource_pool_capacity_exception WHERE pool_id=%s', (child,)).fetchone() == ('Training',)
            expect(tree.get_by_role('treeitem', name='Other', exact=True)).to_have_count(0)
            page.screenshot(path=str(tmp_path / 'pool-tags-filters.png'), full_page=True)
        finally:
            browser.close()


def test_status_selection_changes_peak_and_context_gantt_carries_consuming_projects(authorized, tmp_path):
    from datetime import date, timedelta
    from app.domain.organization.models import Team
    from app.domain.resources.models import PoolMapping
    from app.main import create_organization_service
    from app.runtime import RuntimeResources
    pools = service(authorized)
    parent = pools.create_pool(ResourcePool('Root'))
    child = pools.create_pool(ResourcePool('Delivery', capacity_fte=4, parent_pool_id=parent))
    org = create_organization_service(RuntimeResources(authorized.database, authorized.key), access=authorized.binding(4).access)
    pools.create_mapping(PoolMapping(child, 'team', org.create_team(Team('Delivery team')), 100))
    first = (date.today() + timedelta(days=7)).isoformat()
    last = (date.today() + timedelta(days=10)).isoformat()
    pools.create_assignment(PoolAssignment(child, 1, 99, start_date='2020-01-01', end_date='2020-01-03'))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status=CASE id WHEN 1 THEN 'In Progress' ELSE 'Completed' END")
    pools.create_assignment(PoolAssignment(child, 1, 2, start_date=first, end_date=last))
    pools.create_assignment(PoolAssignment(child, 2, 7, start_date=first, end_date=last))
    screen = SCREEN.replace("render_resource_pools(create_resource_pool_service", """if st.session_state.get('nav_redirect') == 'planning':
    st.success('Gantt navigation queued')
    st.text('Projects: ' + ','.join(map(str, st.session_state['pending_resource_pool_filter']['target_pids'])))
    st.text('Statuses: ' + ','.join(st.session_state['planning_statuses']))
    st.stop()
render_resource_pools(create_resource_pool_service""")
    with native_server(authorized, tmp_path, screen) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1700, 'height': 1100})
            page.goto(server.origin)
            row = page.get_by_role('treeitem', name='Delivery', exact=True)
            expect(row).to_be_visible(timeout=30000)
            expect(row.locator('.pool-meta').last).to_have_text('2.00')
            expect(row.locator('.pool-meta').nth(4)).to_have_text('0.00')
            expect(row.locator('.pool-meta').nth(5)).to_have_text('✓')
            expect(page.get_by_role('treeitem', name='Root', exact=True).locator('.pool-meta').nth(5)).to_have_text('')
            statuses = page.get_by_role('combobox', name='Project statuses included in demand', exact=True)
            statuses.click()
            page.get_by_role('option', name='Completed', exact=True).click()
            statuses.press('Escape')
            expect(row.locator('.pool-meta').last).to_have_text('9.00')
            page.screenshot(path=str(tmp_path / 'current-capacity-statuses.png'), full_page=True)
            row.click(button='right')
            expect(row).to_have_attribute('aria-selected', 'true')
            page.get_by_role('menuitem', name='Show consuming projects in Gantt', exact=True).click()
            expect(page.get_by_text('Gantt navigation queued', exact=True)).to_be_visible()
            expect(page.get_by_text('Projects: 1,2', exact=True)).to_be_visible()
            expect(page.get_by_text('Statuses: In Progress,Completed', exact=True)).to_be_visible()
        finally:
            browser.close()


@pytest.mark.parametrize('target_type', ['team', 'employee'])
def test_context_mapping_saves_leaf_mapping_and_keeps_container_indicator_blank(authorized, tmp_path, target_type):
    import re
    from app.domain.organization.models import Employee, Team
    from app.main import create_organization_service
    from app.runtime import RuntimeResources
    pools = service(authorized)
    parent = pools.create_pool(ResourcePool('Root'))
    leaf = pools.create_pool(ResourcePool('Delivery', parent_pool_id=parent))
    org = create_organization_service(RuntimeResources(authorized.database, authorized.key), access=authorized.binding(4).access)
    org.create_team(Team('Delivery team'))
    org.create_employee(Employee('Ada', 'Lovelace', 'mapping@example.test', 'MAPPING'))
    with native_server(authorized, tmp_path, SCREEN) as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1700, 'height': 1100})
            page.goto(server.origin)
            root = page.get_by_role('treeitem', name='Root', exact=True)
            row = page.get_by_role('treeitem', name='Delivery', exact=True)
            root.click(button='right', timeout=30000)
            expect(page.get_by_role('menuitem', name='Map employees or teams', exact=True)).to_have_count(0)
            root.press('Escape')
            row.click(button='right')
            page.get_by_role('menuitem', name='Map employees or teams', exact=True).click()
            dialog = page.get_by_role('dialog')
            selector = dialog.get_by_role('combobox', name='Teams' if target_type == 'team' else 'Employees', exact=True)
            selector.click()
            page.get_by_role('option', name=re.compile('Delivery team' if target_type == 'team' else 'Ada Lovelace')).click()
            page.get_by_text('Select employees and teams to map.', exact=False).click()
            expect(dialog.get_by_label(re.compile('Allocation'))).to_have_count(1)
            expect(dialog.get_by_label(re.compile('Allocation'))).to_have_value('100.00')
            expect(dialog.get_by_role('button', name='Remove', exact=True)).to_have_count(1)
            page.screenshot(path=str(tmp_path / 'mapping-grid.png'), full_page=True)
            dialog.get_by_role('button', name=re.compile('^Save')).click()
            expect(dialog).to_have_count(0)
            expect(row.locator('.pool-meta').nth(5)).to_have_text('✓')
            expect(root.locator('.pool-meta').nth(5)).to_have_text('')
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT target_type,allocation_pct FROM eppm.resource_pool_mapping WHERE pool_id=%s', (leaf,)).fetchall() == [(target_type, 100)]
            row.click(button='right')
            page.get_by_role('menuitem', name='Map employees or teams', exact=True).click()
            dialog.get_by_role('button', name='Remove', exact=True).click()
            expect(dialog.get_by_label(re.compile('Allocation'))).to_have_count(0)
            expect(dialog.get_by_text('No mappings.', exact=False)).to_be_visible()
            dialog.get_by_role('button', name='Save mappings', exact=True).click()
            expect(dialog).to_have_count(0)
            expect(row.locator('.pool-meta').nth(5)).to_have_text('')
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute(
                    'SELECT id FROM eppm.resource_pool_mapping WHERE pool_id=%s', (leaf,)
                ).fetchall() == []
        finally:
            browser.close()
