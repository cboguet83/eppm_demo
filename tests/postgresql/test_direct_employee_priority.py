"""Global direct priority, safe restoration and partial CSV restoration results."""

from dataclasses import replace
from datetime import date

import psycopg
import pytest

from app.application.services.pool_restoration import PoolRestorationError
from app.application.services.resource_pool_csv import export_pools
from app.domain.organization.models import Employee, EmployeeFunction, EmployeeCalendarException, OrgFunction, Team
from app.domain.resources.models import PoolMapping, ResourcePool
from app.main import create_organization_service, create_resource_pool_service, create_pool_capacity_service
from tests.postgresql.test_resource_pool_ui import database, access, dialog


def split_resources(database, access):
    org = create_organization_service(database, access=access)
    pools = create_resource_pool_service(database, access=access)
    first = org.create_function(OrgFunction('Function A'))
    second = org.create_function(OrgFunction('Function B'))
    employee = org.create_employee(Employee('Employee', 'A', 'a@priority.test', function_assignments=[EmployeeFunction(first, 25), EmployeeFunction(second, 75)]))
    team_a = org.create_team(Team('Team A'), function_ids=[first])
    team_b = org.create_team(Team('Team B'), function_ids=[second])
    x, y, z = [pools.create_pool(ResourcePool(name, capacity_fte=8)) for name in ('X', 'Y', 'Z')]
    pools.create_mapping(PoolMapping(x, 'team', team_a, 100))
    pools.create_mapping(PoolMapping(y, 'team', team_b, 100))
    return org, pools, employee, team_a, team_b, x, y, z


def test_direct_priority_recalculates_other_pools_caches_calendars_and_dashboard(database, access, authorized):
    org, pools, employee, _, _, x, y, z = split_resources(database, access)
    capacity = create_pool_capacity_service(database, access=access)
    assert [row.assigned_capacity_fte for row in capacity.get_details([x, y])] == [.25, .75]
    pools.create_mapping(PoolMapping(z, 'employee', employee, 80))
    assert [row.assigned_capacity_fte for row in capacity.get_details([x, y, z])] == [.05, .15, .8]
    assert pools.mapping_catalog().allocations().total(('employee', employee)) == 100
    # Gross team capacity is deliberately unchanged.
    assert sorted(row.current_fte for row in org.team_overview().capacities.values()) == [.25, .75]
    org.create_employee_calendar_exception(EmployeeCalendarException(employee, date(2026, 1, 1), date(2026, 1, 2), 50))
    details = capacity.calculate_many([x, y, z], date(2026, 1, 1))
    assert [row.daily_assigned_capacity['2026-01-01'] for row in details] == [.025, .075, .4]
    for identity, expected in zip((x, y, z), (.025, .075, .4)):
        calendar = authorized.query('SELECT calendar FROM eppm.pool_effective_capacity(%s::bigint[])', ([identity],))[0][0]
        assert calendar['2026-01-01'] == expected
    org.update_employee(replace(org.get_employee_by_id(employee), occupation_percentage=50))
    assert [row.assigned_capacity_fte for row in capacity.get_details([x, y, z])] == [.025, .075, .4]
    pools.delete_pool(z)
    assert [row.assigned_capacity_fte for row in capacity.get_details([x, y])] == [.125, .375]


def test_same_pool_adds_direct_and_residual_team_share_and_full_direct_member_does_not_block_team(database, access):
    _, pools, employee, team_a, _, x, y, z = split_resources(database, access)
    pools.create_mapping(PoolMapping(x, 'employee', employee, 80))
    capacity = create_pool_capacity_service(database, access=access)
    detail = capacity.calculate_many([x])[0]
    assert detail.assigned_capacity_fte == .85
    assert len(detail.contributing_resources) == 1
    assert 'Team A' in detail.contributing_resources[0].source_name
    direct = next(row for row in pools.get_mappings_by_pool(x) if row.target_type == 'employee')
    pools.update_mapping(direct.id, 100)
    assert capacity.calculate_many([y])[0].assigned_capacity_fte == 0
    # Fully used team A itself is still unavailable; a distinct team with the
    # same fully directly mapped member remains mappable and contributes zero.
    org = create_organization_service(database, access=access)
    other = org.create_team(Team('Other'), function_ids=org.get_team_functions(team_a))
    assert pools.mapping_catalog().remaining(z, 'team', other) == 100
    pools.create_mapping(PoolMapping(z, 'team', other, 100))
    assert capacity.calculate_many([z])[0].effective_capacity_fte == 0


def restoration_conflict(database, access):
    org = create_organization_service(database, access=access)
    pools = create_resource_pool_service(database, access=access)
    employee = org.create_employee(Employee('Ada', 'One', 'restore@priority.test'))
    first = pools.create_pool(ResourcePool('Deleted pool'))
    second = pools.create_pool(ResourcePool('Active pool'))
    pools.create_mapping(PoolMapping(first, 'employee', employee, 80))
    pools.delete_pool(first)
    pools.create_mapping(PoolMapping(second, 'employee', employee, 80))
    return pools, employee, first, second


def test_undelete_rejects_conflict_atomically_and_names_resources_and_pools(database, access):
    pools, employee, first, second = restoration_conflict(database, access)
    with pytest.raises(PoolRestorationError) as error:
        pools.undelete_pool(first)
    assert error.value.warning.pool_id == first
    assert '160%' in str(error.value) and 'Ada One' in str(error.value)
    assert 'Deleted pool: 80%' in str(error.value) and 'Active pool: 80%' in str(error.value)
    assert next(pool for pool in pools.get_all_pools(include_deleted=True) if pool.id == first).deleted_flag
    pools.delete_pool(second)
    assert pools.undelete_pool(first)
    assert pools.get_mappings_by_pool(first)[0].allocation_pct == 80


@pytest.mark.parametrize('delete_missing', [False, True])
def test_csv_keeps_conflicting_restoration_deleted_and_imports_other_updates(database, access, delete_missing):
    pools, _, first, second = restoration_conflict(database, access)
    records = pools.get_all_pools(include_deleted=True)
    rows = [replace(row, deleted_flag=False, description='Imported') for row in records]
    result = pools.import_csv(export_pools(rows).encode(), delete_missing=delete_missing)
    assert len(result.blocked_restorations) == 1
    assert result.blocked_restorations[0].pool_id == first
    assert '160%' in result.blocked_restorations[0].reasons[0]
    records = {row.id: row for row in pools.get_all_pools(include_deleted=True)}
    assert records[first].deleted_flag and records[first].description == 'Imported'
    assert not records[second].deleted_flag and records[second].description == 'Imported'


def test_csv_deletions_are_applied_before_reactivation_validation(database, access):
    pools, _, first, second = restoration_conflict(database, access)
    row = next(row for row in pools.get_all_pools(include_deleted=True) if row.id == first)
    result = pools.import_csv(export_pools([replace(row, deleted_flag=False)]).encode(), delete_missing=True)
    assert result.deactivated == 1 and not result.blocked_restorations
    assert pools.get_pool_by_id(first) and pools.get_pool_by_id(second) is None


def test_csv_collective_conflict_keeps_all_implicated_pools_deleted(database, access):
    pools, _, first, second = restoration_conflict(database, access)
    pools.delete_pool(second)
    rows = [replace(row, deleted_flag=False) for row in pools.get_all_pools(include_deleted=True)]
    result = pools.import_csv(export_pools(rows).encode())
    assert {row.pool_id for row in result.blocked_restorations} == {first, second}
    assert pools.get_all_pools() == []


def test_mapping_mode_defaults_to_teams_and_preserves_both_types_when_switched(database, access):
    _, pools, employee, team_a, _, x, _, _ = split_resources(database, access)
    pools.create_mapping(PoolMapping(x, 'employee', employee, 80))
    app = dialog(database, access, f'_open_add_pool_mapping_dialog(service, {x}, teams, employees)')
    mode = f'direct_employee_mapping_mode_{x}'
    assert not app.checkbox(key=mode).value
    assert not any(widget.label == 'Employees' for widget in app.multiselect)
    assert app.number_input(key=f'mapping_pct_{x}_employee_{employee}').disabled
    app.checkbox(key=mode).check().run()
    assert app.multiselect(key=f'mapping_teams_{x}').disabled
    assert app.number_input(key=f'mapping_pct_{x}_team_{team_a}').disabled
    app.number_input(key=f'mapping_pct_{x}_employee_{employee}').set_value(60).run()
    app.checkbox(key=mode).uncheck().run()
    next(button for button in app.button if button.label == 'Save mappings').click().run()
    assert not app.error and not app.exception
    values = {row.target_type: row.allocation_pct for row in pools.get_mappings_by_pool(x)}
    assert values == {'employee': 60, 'team': 100}


def test_mapping_rows_can_be_removed_in_the_other_mode_without_reappearing(database, access):
    _, pools, employee, team_a, _, x, _, _ = split_resources(database, access)
    pools.create_mapping(PoolMapping(x, 'employee', employee, 80))
    app = dialog(database, access, f'_open_add_pool_mapping_dialog(service, {x}, teams, employees)')
    remove = app.button(key=f'remove_mapping_{x}_employee_{employee}')
    assert not remove.disabled
    remove.click().run()
    app.checkbox(key=f'direct_employee_mapping_mode_{x}').check().run()
    assert app.multiselect(key=f'mapping_employees_{x}').value == []
    remove = app.button(key=f'remove_mapping_{x}_team_{team_a}')
    assert not remove.disabled
    remove.click().run()
    app.checkbox(key=f'direct_employee_mapping_mode_{x}').uncheck().run()
    assert app.multiselect(key=f'mapping_teams_{x}').value == []
    assert len(pools.get_mappings_by_pool(x)) == 2
    next(button for button in app.button if button.label == 'Save mappings').click().run()
    assert not app.error and not app.exception
    assert pools.get_mappings_by_pool(x) == []


def test_direct_mode_handles_existing_employee_with_zero_remaining_allocation(database, access):
    _, pools, employee, _, _, x, _, z = split_resources(database, access)
    pools.create_mapping(PoolMapping(z, 'employee', employee, 100))
    pools.create_mapping(PoolMapping(x, 'employee', employee, 0))
    app = dialog(database, access, f'_open_add_pool_mapping_dialog(service, {x}, teams, employees)')
    app.checkbox(key=f'direct_employee_mapping_mode_{x}').check().run()
    assert not app.error and not app.exception
    widget = app.number_input(key=f'mapping_pct_{x}_employee_{employee}')
    assert widget.value == widget.max == 0.0


def test_csv_keeps_children_deleted_when_their_requested_parent_restoration_is_blocked(database, access):
    pools, _, first, _ = restoration_conflict(database, access)
    rows = [replace(row, deleted_flag=False) for row in pools.get_all_pools(include_deleted=True)]
    rows.append(ResourcePool('New child', parent_pool_id=first))
    result = pools.import_csv(export_pools(rows).encode())
    blocked = {row.pool_name: row for row in result.blocked_restorations}
    assert set(blocked) == {'Deleted pool', 'New child'}
    assert 'Parent pool' in blocked['New child'].reasons[0]
    assert next(pool for pool in pools.get_all_pools(include_deleted=True) if pool.name == 'New child').deleted_flag


def test_csv_deleting_a_direct_pool_reports_new_indirect_overallocation_without_rejecting_import(database, access):
    org, pools, employee, team, _, x, y, z = split_resources(database, access)
    # Two different teams reach the same function in different pools.
    other = org.create_team(Team('Duplicate function team'), function_ids=org.get_team_functions(team))
    pools.create_mapping(PoolMapping(z, 'employee', employee, 100))
    pools.create_mapping(PoolMapping(y, 'team', other, 100))
    rows = [row for row in pools.get_all_pools() if row.id != z]
    result = pools.import_csv(export_pools(rows).encode(), delete_missing=True)
    assert result.deactivated == 1
    assert result.allocation_warnings and '125%' in result.allocation_warnings[0]
    assert pools.get_pool_by_id(z) is None


def test_restoration_and_new_direct_mapping_cannot_concurrently_overallocate(database, access, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, local
    from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolStore

    pools, employee, first, second = restoration_conflict(database, access)
    pools.delete_mapping(pools.get_mappings_by_pool(second)[0].id)
    barrier, state = Barrier(2), local()
    original = PostgresResourcePoolStore.mapping_catalog
    def synchronized(store):
        catalog = original(store)
        if not getattr(state, 'read', False):
            state.read = True
            barrier.wait(timeout=15)
        return catalog
    monkeypatch.setattr(PostgresResourcePoolStore, 'mapping_catalog', synchronized)
    def attempt(restore):
        try:
            if restore:
                pools.undelete_pool(first)
            else:
                pools.create_mapping(PoolMapping(second, 'employee', employee, 80))
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, [True, False])) == [False, True]
    monkeypatch.setattr(PostgresResourcePoolStore, 'mapping_catalog', original)
    assert pools.mapping_catalog().allocations().total(('employee', employee)) == 80


def test_migration_rebuilds_existing_staffing_with_global_priority(empty_database, tmp_path):
    from app.infrastructure.postgresql.migration import discover_migrations, migrate, check_schema

    for migration in discover_migrations()[:55]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        # Migration 55 still requires the level column; migration 60 removes it.
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level) VALUES (1,'Engineer',1)")
        connection.execute("INSERT INTO eppm.employee(employee_id,firstname,lastname,email,employee_code) VALUES (1,'A','One','a@migration.test','A')")
        connection.execute('INSERT INTO eppm.employee_function(employee_id,function_id) VALUES (1,1)')
        connection.execute("INSERT INTO eppm.team(team_id,team_name) VALUES (1,'Team')")
        connection.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES (1,1)')
        connection.execute("INSERT INTO eppm.resource_pool(id,name) VALUES (1,'Team pool'),(2,'Direct pool')")
        connection.execute("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) VALUES (1,'team',1,100),(2,'employee',1,80)")
        connection.execute("INSERT INTO eppm.pool_staffing_projection VALUES (1,1,true,'{}','[]'),(2,.8,true,'{}','[]')")
    assert migrate(empty_database.operator_url) == tuple(item.name for item in discover_migrations()[55:])
    with psycopg.connect(empty_database.operator_url) as connection:
        check_schema(connection)
        assert connection.execute('SELECT assigned_capacity_fte FROM eppm.pool_staffing_projection ORDER BY pool_id').fetchall() == [(.2,), (.8,)]


def test_mapping_mode_resets_on_reopen_and_csv_displays_blocked_restoration_warning(database, access, authorized, tmp_path):
    from tests.postgresql.browser import native_server
    from tests.postgresql.test_pool_hierarchy_browser import SCREEN
    browser_api = pytest.importorskip('playwright.sync_api')
    pools, _, first, second = restoration_conflict(database, access)
    rows = [replace(row, deleted_flag=False) for row in pools.get_all_pools(include_deleted=True)]
    with native_server(authorized, tmp_path, SCREEN) as server, browser_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1600, 'height': 1100})
            page.goto(server.origin)
            row = page.get_by_role('treeitem', name='Active pool', exact=True)
            browser_api.expect(row).to_be_visible(timeout=30000)
            row.click(button='right')
            page.get_by_role('menuitem', name='Map employees or teams').click()
            popup = page.get_by_role('dialog')
            mode = popup.get_by_role('checkbox', name='direct employee mapping mode', exact=True)
            browser_api.expect(mode).not_to_be_checked()
            assert popup.get_by_text('Teams', exact=True).bounding_box()['y'] < mode.bounding_box()['y']
            browser_api.expect(popup.get_by_text('Employees', exact=True)).to_have_count(0)
            popup.get_by_text('direct employee mapping mode', exact=True).click()
            browser_api.expect(popup.get_by_text('Employees', exact=True)).to_be_visible()
            page.screenshot(path=str(tmp_path / 'direct-mapping-mode.png'), full_page=True)
            popup.get_by_role('button', name='Cancel', exact=True).click()
            browser_api.expect(popup).to_have_count(0)
            row.click(button='right')
            page.get_by_role('menuitem', name='Map employees or teams').click()
            browser_api.expect(mode).not_to_be_checked()
            popup.get_by_text('direct employee mapping mode', exact=True).click()
            popup.get_by_role('button', name='Close', exact=True).click()
            browser_api.expect(popup).to_have_count(0)
            row.click(button='right')
            page.get_by_role('menuitem', name='Map employees or teams').click()
            browser_api.expect(mode).not_to_be_checked()
            popup.get_by_role('button', name='Cancel', exact=True).click()
            browser_api.expect(popup).to_have_count(0)
            page.get_by_role('button', name='Import CSV').click()
            popup.locator('input[type="file"]').set_input_files({
                'name': 'restore.csv', 'mimeType': 'text/csv', 'buffer': export_pools(rows).encode()})
            browser_api.expect(popup.get_by_text('2 pool records ready to import.')).to_be_visible()
            popup.get_by_text('Delete pools missing from the uploaded CSV', exact=True).click()
            popup.get_by_role('button', name='Import pools', exact=True).click()
            browser_api.expect(page.get_by_text('Import successful: 0 pools created, 2 updated, 0 marked deleted.')).to_be_visible()
            browser_api.expect(page.get_by_text(f'Deleted pool (#{first}) remains deleted:', exact=False)).to_contain_text('160%')
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert dict(connection.execute('SELECT id,deleted_flag FROM eppm.resource_pool')) == {first: True, second: False}
            browser_api.expect(popup).to_have_count(0)
            page.screenshot(path=str(tmp_path / 'csv-restoration-warning.png'), full_page=True)
        finally:
            browser.close()
