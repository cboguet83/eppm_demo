"""Atomic employee edits, code removal, warnings and directory presentation."""

from dataclasses import replace
from datetime import date, timedelta

import psycopg
import pytest

from app.domain.organization.models import Employee, EmployeeCalendarException, EmployeeFunction, OrgFunction, Team
from app.domain.resources.models import PoolAssignment, ResourcePool
from app.infrastructure.postgresql.migration import discover_migrations, migrate
from app.infrastructure.postgresql.staffing_projection import refresh_staffing
from app.main import create_organization_service, create_resource_pool_service
from tests.postgresql.test_resource_pool_ui import database, access


def test_profile_save_updates_all_sections_or_rolls_back(database, access):
    organization = create_organization_service(database, access=access)
    function = organization.create_function(OrgFunction('Engineer', 1))
    identity = organization.create_employee(Employee('Ada', 'One', 'ada@profile.test', function_id=function))
    person = organization.get_employee_by_id(identity)
    exception = EmployeeCalendarException(identity, date(2026, 1, 1), date(2026, 1, 3), 25)
    changed = replace(person, occupation_percentage=80, function_assignments=[EmployeeFunction(function, 50)])
    organization.update_employee(changed, exceptions=[exception])
    saved = organization.get_employee_by_id(identity)
    calendar = organization.get_employee_calendar_exceptions(identity)
    assert saved.occupation_percentage == 80 and saved.assignments() == [EmployeeFunction(function, 50)]
    assert calendar[0].occupation_percentage == 25
    with pytest.raises(ValueError, match='overlap'):
        organization.update_employee(replace(saved, firstname='Lost', occupation_percentage=55),
            exceptions=[exception, replace(exception, start_date=date(2026, 1, 3))])
    assert organization.get_employee_by_id(identity) == saved
    assert organization.get_employee_calendar_exceptions(identity) == calendar
    with pytest.raises(ValueError, match='stale'):
        organization.update_employee(replace(saved, firstname='Lost'), exceptions=[replace(exception, exception_id=9999)])
    assert organization.get_employee_by_id(identity) == saved
    organization.update_employee(saved, exceptions=[])
    assert organization.get_employee_calendar_exceptions(identity) == []


def test_employee_code_migration_preserves_identity_membership_and_calendar(empty_database, tmp_path):
    for migration in discover_migrations()[:56]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level) VALUES (1,'Engineer',1)")
        connection.execute("INSERT INTO eppm.employee(employee_id,firstname,lastname,email,employee_code) VALUES (7,'Ada','One','a@profile.test','OLD')")
        connection.execute('INSERT INTO eppm.employee_function VALUES (7,1,80)')
        connection.execute("INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage) VALUES (7,'2026-01-01','2026-01-03',50)")
    assert migrate(empty_database.operator_url) == ('0057_remove_employee_code.sql',)
    with psycopg.connect(empty_database.operator_url) as connection:
        assert not connection.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='eppm' AND table_name='employee' AND column_name='employee_code'").fetchall()
        assert connection.execute('SELECT employee_id,firstname FROM eppm.active_employee').fetchall() == [(7, 'Ada')]
        assert connection.execute('SELECT * FROM eppm.active_employee_function').fetchall() == [(7, 1, 80)]
        assert connection.execute('SELECT occupation_percentage FROM eppm.employee_calendar_exception').fetchone() == (50,)
    assert migrate(empty_database.operator_url) == ()


def test_employee_editor_percentages_and_calendar_save_with_profile(database, access):
    from tests.postgresql.test_organization_ui import dialog, button

    organization = create_organization_service(database, access=access)
    function = organization.create_function(OrgFunction('Analyst', 1))
    identity = organization.create_employee(Employee('Ada', 'One', 'edit@profile.test', function_id=function))
    app = dialog(database, access, f'_open_edit_employee_dialog(service, {identity}, functions)')
    assert not any('Code' in widget.label for widget in app.text_input)
    button(app, 'Add calendar exception').click().run()
    assert not any(widget.label == 'Save calendar exceptions' for widget in app.button)
    for widget in app.number_input:
        assert widget.proto.step == 5
        assert widget.proto.format == '%.0f'
    next(widget for widget in app.number_input if widget.label == 'Availability (%)').set_value(35).run()
    assert organization.get_employee_calendar_exceptions(identity) == []
    next(widget for widget in app.number_input if widget.label == 'Employee Overall occupation').set_value(85)
    next(widget for widget in app.number_input if widget.label == 'Allocation (%)').set_value(70)
    button(app, 'Save Changes').click().run()
    assert not app.exception and not app.error
    assert organization.get_employee_by_id(identity).occupation_percentage == 85
    assert organization.get_employee_by_id(identity).assignments() == [EmployeeFunction(function, 70)]
    assert organization.get_employee_calendar_exceptions(identity)[0].occupation_percentage == 35


def test_pool_warning_overlay_and_only_employee_overallocation_colors_names(database, access, authorized, tmp_path):
    from tests.postgresql.browser import native_server
    from tests.postgresql.test_pool_hierarchy_browser import SCREEN

    api = pytest.importorskip('playwright.sync_api')
    organization = create_organization_service(database, access=access)
    pools = create_resource_pool_service(database, access=access)
    function = organization.create_function(OrgFunction('Engineer', 1))
    employee = organization.create_employee(Employee('Ada', 'One', 'warning@profile.test', function_id=function))
    team = organization.create_team(Team('Vacant team'))
    identities = [pools.create_pool(ResourcePool(name, capacity_fte=1)) for name in
                  ('Employee first', 'Employee second', 'Team first', 'Team second', 'Demand only')]
    today = date.today()
    pools.create_assignment(PoolAssignment(identities[-1], 1, 2, start_date=(today + timedelta(days=1)).isoformat(),
                                          end_date=(today + timedelta(days=2)).isoformat()))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        for index, pool in enumerate(identities[:4]):
            connection.execute('INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) VALUES (%s,%s,%s,60)',
                               (pool, 'employee' if index < 2 else 'team', employee if index < 2 else team))
        refresh_staffing(connection)
    with native_server(authorized, tmp_path, SCREEN) as server, api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1700, 'height': 1100})
            page.goto(server.origin)
            tree = page.get_by_role('tree', name='Resource pools')
            api.expect(tree).to_be_visible(timeout=30000)
            for name in ('Employee first', 'Employee second'):
                api.expect(tree.get_by_role('treeitem', name=name, exact=True).locator('.pool-name')).to_have_css('color', 'rgb(196, 16, 57)')
            for name in ('Team first', 'Team second', 'Demand only'):
                api.expect(tree.get_by_role('treeitem', name=name, exact=True).locator('.pool-name')).not_to_have_css('color', 'rgb(196, 16, 57)')
            api.expect(tree.get_by_role('treeitem', name='Demand only', exact=True).locator('.pool-warning')).to_be_visible()
            metric = page.locator('.st-key-overallocated_resources')
            metric.locator('[data-testid="stTooltipIcon"]').hover()
            tooltip = page.get_by_role('tooltip')
            api.expect(tooltip).to_be_visible()
            api.expect(tooltip).to_contain_text('Ada One: 120% allocated')
            api.expect(tooltip).to_contain_text('Engineer (100%)')
            api.expect(tooltip).to_contain_text('Vacant team: 120% allocated')
            page.screenshot(path=str(tmp_path / 'pool-warning-details.png'), full_page=True)
        finally:
            browser.close()


def test_employee_directory_default_sort_and_zero_decimal_rendering(database, access, authorized, tmp_path):
    from tests.postgresql.browser import native_server
    from tests.postgresql.test_pool_hierarchy_browser import SCREEN

    api = pytest.importorskip('playwright.sync_api')
    organization = create_organization_service(database, access=access)
    identities = [organization.create_employee(Employee(first, last, email, occupation_percentage=85))
                  for first, last, email in [('Zoe', 'Zulu', 'z@sort.test'), ('Ada', 'Alpha', 'a@sort.test'), ('Ada', 'Alpha', 'b@sort.test')]]
    assert [person.employee_id for person in organization.get_all_employees()] == [identities[1], identities[2], identities[0]]
    assert 'employee_code' not in organization.export_csv('employees').splitlines()[0]
    screen = SCREEN[:SCREEN.index('render_resource_pools(create_resource_pool_service')] + '''
from app.presentation.pages.organization import render_employees
render_employees(create_organization_service(runtime, access=access))
'''
    with native_server(authorized, tmp_path, screen) as server, api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = server.new_page(browser, viewport={'width': 1700, 'height': 1100})
            page.goto(server.origin)
            frame = page.frame_locator('iframe').first
            rows = frame.locator('tbody tr[data-id]')
            api.expect(rows).to_have_count(3, timeout=30000)
            for index, identity in enumerate([identities[1], identities[2], identities[0]]):
                api.expect(rows.nth(index)).to_have_attribute('data-id', str(identity))
            api.expect(frame.get_by_role('columnheader', name='Code', exact=True)).to_have_count(0)
            api.expect(rows.first.locator('.badge-occupation')).to_have_text('85%')
            page.screenshot(path=str(tmp_path / 'employee-directory.png'), full_page=True)
            rows.first.click(button='right')
            frame.get_by_text('Edit Employee Profile', exact=True).click()
            popup = page.get_by_role('dialog')
            occupation = popup.get_by_role('spinbutton', name='Employee Overall occupation', exact=True)
            api.expect(occupation).to_have_value('85')
            popup.get_by_role('button', name='Add calendar exception', exact=True).click()
            availability = popup.get_by_role('spinbutton', name='Availability (%)', exact=True)
            api.expect(availability).to_have_value('85')
            availability.fill('35')
            availability.press('Tab')
            api.expect(popup.get_by_role('button', name='Save calendar exceptions', exact=True)).to_have_count(0)
            api.expect(popup.get_by_role('textbox', name='Employee Code', exact=False)).to_have_count(0)
            page.screenshot(path=str(tmp_path / 'employee-profile.png'), full_page=True)
            popup.get_by_role('button', name='Cancel', exact=True).click()
            api.expect(popup).to_have_count(0)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                assert connection.execute('SELECT count(*) FROM eppm.employee_calendar_exception').fetchone() == (0,)
            rows.first.click(button='right')
            frame.get_by_text('Edit Employee Profile', exact=True).click()
            api.expect(popup.get_by_role('spinbutton', name='Availability (%)', exact=True)).to_have_count(0)
        finally:
            browser.close()
