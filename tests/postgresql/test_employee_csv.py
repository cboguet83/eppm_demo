"""Employee imports preserve histories and commit validated catalogs atomically."""

import csv
from datetime import date
from io import StringIO
import json

import psycopg
import pytest

from app.application.services.employee_csv import parse_employees
from app.domain.organization.models import Employee, EmployeeCalendarException, EmployeeFunction, OrgFunction
from tests.postgresql.test_organization import organization


def document(rows):
    output = StringIO()
    writer = csv.DictWriter(output, list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode('utf-8')


def test_employee_import_updates_creates_and_preserves_calendars_and_mappings(organization, authorized):
    function = organization.create_function(OrgFunction('Engineer'))
    identity = organization.create_employee(Employee('Ada', 'One', 'ada@example.test', function_id=function))
    other = organization.create_employee(Employee('Other', 'Person', 'other@example.test'))
    exception = organization.create_employee_calendar_exception(
        EmployeeCalendarException(identity, date(2027, 1, 1), date(2027, 1, 2), 50))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name) VALUES(1,'Pool')")
        connection.execute("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id) VALUES(1,'employee',%s)", (identity,))
    result = organization.import_employees_csv(document([
        dict(employee_id=identity, firstname='Ada', lastname='Updated', email='ada@example.test', occupation_percentage=80),
        dict(employee_id=999999, firstname='New', lastname='Person', email='new@example.test', occupation_percentage=50),
    ]))
    assert (result.created, result.updated, result.deleted) == (1, 1, 0)
    employees = organization.get_all_employees()
    assert len(employees) == 3
    assert next(item for item in employees if item.firstname == 'New').employee_id != 999999
    assert organization.get_employee_by_id(identity).assignments() == [EmployeeFunction(function)]
    assert organization.get_employee_calendar_exception_by_id(exception).occupation_percentage == 50
    assert organization.get_employee_by_id(other) is not None
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT assigned_capacity_fte FROM eppm.pool_staffing_projection WHERE pool_id=1').fetchone()[0] == .8
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_mapping').fetchone()[0] == 1


def test_employee_export_roundtrip_soft_delete_restore_and_clear_functions(organization):
    function = organization.create_function(OrgFunction('Engineer'))
    identity = organization.create_employee(Employee('João', 'Silva', 'joao@example.test', function_id=function,
                                                     mobile='+351123456789'))
    other = organization.create_employee(Employee('Other', 'Person', 'other@example.test'))
    exported = organization.export_csv('employees')
    assert organization.import_employees_csv(exported.encode()).updated == 2
    assert organization.get_employee_by_id(identity).mobile == '+351123456789'
    rows = list(csv.DictReader(StringIO(exported)))
    row = next(row for row in rows if int(row['employee_id']) == identity)
    row['function_assignments'] = '[]'
    result = organization.import_employees_csv(document([row]), delete_missing=True)
    assert result.deleted == 1
    assert organization.get_employee_by_id(other) is None
    assert organization.get_employee_by_id(identity).assignments() == []
    row['deleted_flag'] = 'true'
    organization.import_employees_csv(document([row]))
    assert not organization.get_all_employees()
    assert len(parse_employees(organization.export_csv('employees', include_deleted=True).encode())) == 2
    row['deleted_flag'] = 'false'
    organization.import_employees_csv(document([row]))
    assert organization.get_employee_by_id(identity).firstname == 'João'


def test_employee_import_supports_template_shorthand_and_multiple_function_shares(organization):
    first = organization.create_function(OrgFunction('Engineer'))
    second = organization.create_function(OrgFunction('Manager'))
    organization.import_employees_csv(
        f'\ufefffirstname;lastname;email;function_id;function_assignments\nA;One;a@x.test;{first};\n'.encode())
    employee = organization.get_all_employees()[0]
    assert employee.assignments() == [EmployeeFunction(first)]
    result = organization.import_employees_csv(document([dict(employee_id=employee.employee_id,
        firstname='A', lastname='One', email='a@x.test', function_assignments=json.dumps([
            dict(function_id=first, allocation_pct=25), dict(function_id=second, allocation_pct=75)]))]))
    assert result.updated == 1
    assert organization.get_employee_by_id(employee.employee_id).assignments() == [
        EmployeeFunction(first, 25), EmployeeFunction(second, 75)]


@pytest.mark.parametrize('problem', ['overallocated', 'unknown_function', 'duplicate_email'])
def test_invalid_later_employee_rolls_back_entire_import(organization, problem):
    function = organization.create_function(OrgFunction('Engineer'))
    second = organization.create_function(OrgFunction('Manager'))
    organization.create_employee(Employee('Existing', 'Person', 'existing@example.test'))
    assignments = ([{'function_id': function, 'allocation_pct': 70}, {'function_id': second, 'allocation_pct': 40}]
                   if problem == 'overallocated' else [{'function_id': 999999, 'allocation_pct': 100}]
                   if problem == 'unknown_function' else [])
    payload = document([
        dict(firstname='Valid', lastname='New', email='valid@example.test', function_assignments='[]'),
        dict(firstname='Invalid', lastname='New', email='existing@example.test' if problem == 'duplicate_email' else 'invalid@example.test',
             function_assignments=json.dumps(assignments)),
    ])
    with pytest.raises(ValueError, match='Row 3'):
        organization.import_employees_csv(payload, delete_missing=True)
    assert [item.firstname for item in organization.get_all_employees()] == ['Existing']


@pytest.mark.parametrize('content, message', [
    (b'firstname,lastname,email\n', 'no employee records'),
    (b'firstname,lastname,email\nA,B,bad\n', 'Row 2.*email'),
    (b'firstname,lastname,email,occupation_percentage\nA,B,a@x.test,NaN\n', 'Row 2.*Occupation'),
    (b'firstname,lastname,email,deleted_flag\nA,B,a@x.test,yes\n', 'Row 2.*deleted_flag'),
    (b'firstname,lastname,email,function_assignments\nA,B,a@x.test,{}\n', 'Row 2.*function_assignments'),
    (b'firstname,lastname,email,employee_code\nA,B,a@x.test,X\n', 'Unsupported'),
    (b'firstname,lastname,email\n\xff,B,a@x.test\n', 'UTF-8'),
])
def test_employee_csv_reports_invalid_input(content, message):
    with pytest.raises(ValueError, match=message):
        parse_employees(content)
