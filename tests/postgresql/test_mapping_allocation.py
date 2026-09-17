"""Real transactions, restored pools and mapping popup allocation limits."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local
import re

import pytest

from app.domain.organization.models import Employee, OrgFunction, Team
from app.domain.resources.models import PoolMapping, ResourcePool
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolStore
from app.main import create_organization_service, create_resource_pool_service
from tests.postgresql.test_resource_pool_ui import database, access, dialog
from tests.postgresql.browser import native_server
from tests.postgresql.test_pool_hierarchy_browser import SCREEN


def setup_resources(database, access):
    service = create_resource_pool_service(database, access=access)
    org = create_organization_service(database, access=access)
    first = service.create_pool(ResourcePool('Alpha'))
    second = service.create_pool(ResourcePool('Beta'))
    function = org.create_function(OrgFunction('Engineer', 1))
    team = org.create_team(Team('Delivery'), function_ids=[function])
    employee = org.create_employee(Employee('Ada', 'One', 'ada@example.test', 'ADA', function_id=function))
    return service, first, second, team, employee


def test_all_write_paths_reject_excess_and_restore_exposes_warning(database, access):
    service, first, second, team, employee = setup_resources(database, access)
    service.create_mapping(PoolMapping(first, 'team', team, 60))
    with pytest.raises(ValueError, match='cannot exceed 100%'):
        service.create_mapping(PoolMapping(second, 'employee', employee, 50))
    mapping = service.create_mapping(PoolMapping(second, 'employee', employee, 40))
    with pytest.raises(ValueError):
        service.update_mapping(mapping, 41)
    with pytest.raises(ValueError):
        service.save_mappings(second, [PoolMapping(second, 'team', team, 50)])
    assert service.get_mappings_by_pool(second)[0].allocation_pct == 40
    service.delete_pool(first)
    service.update_mapping(mapping, 100)
    assert not service.mapping_catalog().allocations().overallocated
    service.undelete_pool(first)
    result = service.mapping_catalog().allocations()
    assert result.overallocated == {('employee', employee)}
    assert set(result.pool_warnings()) == {first, second}
    assert 'Alpha: 60%' in result.warning(('employee', employee))
    service.update_mapping(mapping, 40)
    assert not service.mapping_catalog().allocations().overallocated


def test_popup_filters_exhausted_resources_and_defaults_to_remaining(database, access):
    service, first, second, team, employee = setup_resources(database, access)
    service.create_mapping(PoolMapping(first, 'team', team, 65))
    app = dialog(database, access, f'_open_add_pool_mapping_dialog(service, {second}, teams, employees)')
    app.multiselect(key=f'mapping_employees_{second}').set_value([employee]).run()
    widget = app.number_input(key=f'mapping_pct_{second}_employee_{employee}')
    assert widget.value == 35 and widget.max == 35
    next(button for button in app.button if button.label == 'Save mappings').click().run()
    assert not app.exception and not app.error
    third = service.create_pool(ResourcePool('Gamma'))
    app = dialog(database, access, f'_open_add_pool_mapping_dialog(service, {third}, teams, employees)')
    assert app.multiselect(key=f'mapping_employees_{third}').options == []
    assert app.multiselect(key=f'mapping_teams_{third}').options == []


def test_removing_direct_override_cannot_expose_excess_team_allocation(database, access):
    service, first, second, team, employee = setup_resources(database, access)
    service.create_mapping(PoolMapping(first, 'team', team, 100))
    direct = service.create_mapping(PoolMapping(first, 'employee', employee, 20))
    service.create_mapping(PoolMapping(second, 'employee', employee, 80))
    with pytest.raises(ValueError, match='cannot exceed 100%'):
        service.delete_mapping(direct)
    assert service.mapping_catalog().allocations().total(('employee', employee)) == 100


def test_concurrent_allocations_cannot_both_consume_same_remaining_capacity(database, access, monkeypatch):
    service, first, second, _, employee = setup_resources(database, access)
    barrier, state = Barrier(2), local()
    original = PostgresResourcePoolStore.mapping_catalog
    def synchronized(store):
        result = original(store)
        if not getattr(state, 'read', False):
            state.read = True
            barrier.wait(timeout=15)
        return result
    monkeypatch.setattr(PostgresResourcePoolStore, 'mapping_catalog', synchronized)
    def allocate(pool):
        try:
            service.create_mapping(PoolMapping(pool, 'employee', employee, 60))
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(allocate, [first, second]))
    assert sorted(results) == [False, True]
    monkeypatch.setattr(PostgresResourcePoolStore, 'mapping_catalog', original)
    assert service.mapping_catalog().allocations().total(('employee', employee)) == 60


def test_restored_pool_warning_overlay_and_zero_remaining_editor(database, access, authorized, tmp_path):
    playwright_api = pytest.importorskip('playwright.sync_api')
    service, first, second, _, employee = setup_resources(database, access)
    service.create_mapping(PoolMapping(first, 'employee', employee, 100))
    service.delete_pool(first)
    service.create_mapping(PoolMapping(second, 'employee', employee, 100))
    service.undelete_pool(first)
    with native_server(authorized, tmp_path, SCREEN) as server, playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1700, 'height': 1200})
            page.goto(server.origin)
            row = page.get_by_role('treeitem', name='Alpha', exact=True)
            playwright_api.expect(row).to_be_visible(timeout=30000)
            playwright_api.expect(row.locator('.pool-warning')).to_have_attribute('title', re.compile('200%'))
            warning = page.locator('.allocation-warning')
            warning.hover()
            tooltip = warning.get_by_role('tooltip')
            playwright_api.expect(tooltip).to_be_visible()
            playwright_api.expect(tooltip).to_contain_text('Alpha: 100%; Beta: 100%')
            page.screenshot(path=str(tmp_path / 'mapping-warnings.png'), full_page=True)
            row.click(button='right')
            page.get_by_role('menuitem', name='Map employees or teams').click()
            popup = page.get_by_role('dialog')
            playwright_api.expect(popup.get_by_text('Only 0% remains across active pools.')).to_be_visible()
            playwright_api.expect(popup.get_by_role('spinbutton')).to_have_value('0.00')
        finally:
            browser.close()
