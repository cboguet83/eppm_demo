"""Weighted employee functions, migration preservation and private staffing reads."""

from dataclasses import replace
from datetime import date

import psycopg
import pytest

from app.domain.organization.models import Employee, EmployeeFunction, OrgFunction, Team, EmployeeCalendarException
from app.domain.resources.models import PoolMapping, ResourcePool
from app.main import create_organization_service, create_resource_pool_service, create_pool_capacity_service
from app.infrastructure.postgresql.migration import discover_migrations, migrate, check_schema
from tests.postgresql.test_resource_pool_ui import database, access


def test_migration_preserves_every_existing_function_link_at_100_percent(empty_database, tmp_path):
    for migration in discover_migrations()[:54]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level) VALUES (1,'Engineer',1)")
        connection.execute("INSERT INTO eppm.employee(employee_id,firstname,lastname,email,employee_code,function_id,deleted_flag) "
            "VALUES (1,'A','One','a@x.test','A',1,false),(2,'B','Two','b@x.test','B',1,true),(3,'C','Three','c@x.test','C',NULL,false)")
        connection.execute("INSERT INTO eppm.resource_pool(id,name) VALUES (1,'Existing pool')")
        connection.execute("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id) VALUES (1,'employee',1)")
    migrate(empty_database.operator_url)
    with psycopg.connect(empty_database.operator_url) as connection:
        check_schema(connection)
        assert connection.execute('SELECT employee_id,function_id,allocation_pct FROM eppm.employee_function ORDER BY employee_id').fetchall() == [(1, 1, 100), (2, 1, 100)]
        assert connection.execute('SELECT assigned_capacity_fte FROM eppm.pool_staffing_projection WHERE pool_id=1').fetchone() == (1,)
    assert migrate(empty_database.operator_url) == ()


def setup_split(database, access):
    org = create_organization_service(database, access=access)
    pools = create_resource_pool_service(database, access=access)
    first = org.create_function(OrgFunction('Engineer', 1))
    second = org.create_function(OrgFunction('Analyst', 1))
    employee = org.create_employee(Employee('Ada', 'One', 'ada@x.test', occupation_percentage=80,
        function_assignments=[EmployeeFunction(first, 60), EmployeeFunction(second, 40)]))
    team_a = org.create_team(Team('Engineering'), function_ids=[first])
    team_b = org.create_team(Team('Analysis'), function_ids=[second])
    pool_a = pools.create_pool(ResourcePool('Pool A'))
    pool_b = pools.create_pool(ResourcePool('Pool B'))
    pools.create_mapping(PoolMapping(pool_a, 'team', team_a, 100))
    pools.create_mapping(PoolMapping(pool_b, 'team', team_b, 100))
    return org, pools, employee, first, second, team_a, team_b, pool_a, pool_b


def test_split_functions_weight_team_and_pool_capacity_and_employee_exceptions(database, access, authorized):
    org, pools, employee, first, second, team_a, team_b, pool_a, pool_b = setup_split(database, access)
    person = org.get_employee_by_id(employee)
    assert person.function_id is None
    assert person.assignments() == [EmployeeFunction(first, 60), EmployeeFunction(second, 40)]
    overview = org.team_overview(today=date(2026, 1, 1))
    assert overview.capacities[team_a].current_fte == .48
    assert overview.capacities[team_b].current_fte == .32
    org.create_employee_calendar_exception(EmployeeCalendarException(employee, date(2026, 1, 1), date(2026, 1, 2), 50))
    capacity = create_pool_capacity_service(database, access=access)
    details = capacity.calculate_many([pool_a, pool_b], date(2026, 1, 1))
    assert [row.assigned_capacity_fte for row in details] == [.48, .32]
    assert [row.daily_assigned_capacity['2026-01-01'] for row in details] == [.3, .2]
    assert pools.mapping_catalog().allocations().total(('employee', employee)) == 100
    public = authorized.query('SELECT * FROM eppm.pool_staffing(%s::bigint[])', ([pool_a, pool_b],), user_id=1)
    assert [row[1] for row in public] == [.48, .32]
    assert all(row[4] == [] for row in public)
    assert authorized.query('SELECT * FROM eppm.employee_function', user_id=1) == []


def test_function_total_is_validated_atomically_and_deleted_functions_do_not_count(database, access):
    org, _, employee, first, second, *_ = setup_split(database, access)
    person = org.get_employee_by_id(employee)
    with pytest.raises(ValueError, match='cannot exceed 100%'):
        org.update_employee(replace(person, firstname='Lost', function_assignments=[EmployeeFunction(first, 70), EmployeeFunction(second, 40)]))
    assert org.get_employee_by_id(employee) == person
    org.delete_function(second)
    org.update_employee(replace(person, function_assignments=[EmployeeFunction(first, 100), EmployeeFunction(second, 40)]))
    assert len(org.get_employee_by_id(employee).assignments()) == 2
    with pytest.raises(ValueError, match='once'):
        org.update_employee(replace(person, function_assignments=[EmployeeFunction(first, 50), EmployeeFunction(first, 50)]))


def test_employee_exception_grid_adds_edits_removes_and_rolls_back_overlap(database, access):
    org, _, employee, *_ = setup_split(database, access)
    first = EmployeeCalendarException(employee, date(2026, 1, 1), date(2026, 1, 3), 25)
    second = EmployeeCalendarException(employee, date(2026, 2, 1), date(2026, 2, 3), 50)
    org.replace_employee_exceptions(employee, [first, second])
    assert len(org.get_employee_calendar_exceptions(employee)) == 2
    with pytest.raises(ValueError, match='overlap'):
        org.replace_employee_exceptions(employee, [first, replace(second, start_date=date(2026, 1, 3))])
    assert len(org.get_employee_calendar_exceptions(employee)) == 2
    org.replace_employee_exceptions(employee, [replace(first, occupation_percentage=75)])
    assert org.get_employee_calendar_exceptions(employee)[0].occupation_percentage == 75
    org.replace_employee_exceptions(employee, [])
    assert org.get_employee_calendar_exceptions(employee) == []


def test_team_unmapping_names_affected_employees_and_requires_confirmation(database, access):
    from tests.postgresql.ui import native_screen

    org, pools, employee, first, _, team, _, pool, _ = setup_split(database, access)
    colleague = org.create_employee(Employee('Ben', 'Two', 'ben@x.test', function_id=first))
    script = f'''
from app.main import create_resource_pool_service
from app.presentation.components.pool_detail_actions import confirm_unmap
service = create_resource_pool_service(runtime, access=access)
confirm_unmap(service, {pool}, 'employee', {employee}, 'Ada One')
'''
    app = native_screen(script, database, access).run()
    assert not app.exception
    assert 'Engineering' in app.warning[0].value
    assert 'Ada One' in app.warning[0].value and 'Ben Two' in app.warning[0].value
    assert len(pools.get_mappings_by_pool(pool)) == 1
    next(button for button in app.button if button.label == 'Cancel').click().run()
    assert len(pools.get_mappings_by_pool(pool)) == 1
    next(button for button in app.button if button.label == 'Confirm unmap').click().run()
    assert not app.exception
    assert pools.get_mappings_by_pool(pool) == []
    assert org.get_team_by_id(team) is not None
    assert org.get_employee_by_id(employee) is not None
    assert org.get_employee_by_id(colleague) is not None


def test_employee_profile_grid_saves_multiple_functions_and_rejects_excess(database, access):
    from tests.postgresql.test_organization_ui import dialog, button

    org, _, employee, first, second, *_ = setup_split(database, access)
    app = dialog(database, access, f'_open_edit_employee_dialog(service, {employee}, functions)')

    occupation = app.number_input[0]
    assert occupation.label == 'Employee Overall occupation'
    assert occupation.value == 80
    assert occupation.proto.help == 'Full time employee has an occupation of 100%, half time employee has an occupation of 50%.'

    allocations = [widget for widget in app.number_input if widget.label == 'Allocation (%)']
    allocations[0].set_value(55)
    allocations[1].set_value(45)
    button(app, 'Save Changes').click().run()
    assert not app.exception
    assert org.get_employee_by_id(employee).assignments() == [EmployeeFunction(first, 55), EmployeeFunction(second, 45)]
    next(widget for widget in app.number_input if widget.label == 'Allocation (%)').set_value(70)
    button(app, 'Save Changes').click().run()
    assert not app.exception
    assert any('100%' in item.value for item in app.error)
    assert org.get_employee_by_id(employee).assignments() == [EmployeeFunction(first, 55), EmployeeFunction(second, 45)]
    deletes = [widget for widget in app.button if widget.label == 'Delete']
    deletes[1].click().run()
    assert len([widget for widget in app.number_input if widget.label == 'Allocation (%)']) == 1
    assert org.get_employee_by_id(employee).assignments() == [EmployeeFunction(first, 55), EmployeeFunction(second, 45)]
    button(app, 'Save Changes').click().run()
    assert org.get_employee_by_id(employee).assignments() == [EmployeeFunction(first, 70)]
    button(app, 'Add function assignment').click().run()
    app.selectbox[-1].set_value(second)
    [widget for widget in app.number_input if widget.label == 'Allocation (%)'][-1].set_value(30)
    button(app, 'Save Changes').click().run()
    assert not app.exception and not app.error
    assert org.get_employee_by_id(employee).assignments() == [EmployeeFunction(first, 70), EmployeeFunction(second, 30)]


def test_employee_overallocation_warning_and_profile_grids_in_browser(database, access, authorized, tmp_path):
    from tests.postgresql.browser import native_server
    from app.infrastructure.postgresql.staffing_projection import refresh_staffing

    browser_api = pytest.importorskip('playwright.sync_api')
    _, _, employee, *_ = setup_split(database, access)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.employee_function SET allocation_pct=60 WHERE employee_id=%s', (employee,))
        refresh_staffing(connection)
    script = '''
import streamlit as st
from app.runtime import process_runtime
from app.application.services.business_access import BusinessAccess
from tests.postgresql.browser import browser_access
from app.presentation.i18n import set_current_locale
from app.main import create_organization_service
from app.presentation.pages.organization import render_employees
st.set_page_config(layout='wide')
runtime = process_runtime()
authentication = browser_access(runtime)
actor = authentication.actor(st.context.cookies.get('eppm_session', ''))
access = BusinessAccess(actor, authentication.policy)
set_current_locale('en')
render_employees(create_organization_service(runtime, access=access))
'''
    with native_server(authorized, tmp_path, script) as server, browser_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1700, 'height': 1200})
            page.goto(server.origin)
            frame = page.frame_locator('iframe').first
            row = frame.locator('tr.employee-overallocated')
            browser_api.expect(row).to_be_visible(timeout=30000)
            browser_api.expect(row.locator('[title*="120%"]')).to_be_visible()
            browser_api.expect(row.locator('td').first).to_have_css('color', 'rgb(196, 16, 57)')
            row.click(button='right')
            frame.get_by_text('Edit Employee Profile', exact=True).click()
            popup = page.get_by_role('dialog')
            browser_api.expect(popup.get_by_text('Function assignments', exact=True)).to_be_visible()
            browser_api.expect(popup.get_by_text('Employee Calendar Exceptions', exact=True)).to_be_visible()
            browser_api.expect(popup.get_by_role('button', name='Delete', exact=True)).to_have_count(2)
            popup.get_by_role('button', name='Add calendar exception', exact=True).click()
            browser_api.expect(popup.get_by_role('button', name='Delete', exact=True)).to_have_count(3)
            browser_api.expect(popup.locator('[data-testid="stSkeleton"]')).to_have_count(0)
            browser_api.expect(popup.get_by_role('button', name='Save Changes', exact=True)).to_be_visible()
            page.screenshot(path=str(tmp_path / 'employee-grids.png'), full_page=True)
        finally:
            browser.close()
