"""Employee CSV parsing and atomic catalog updates, preserving calendars."""

import csv
import json
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from io import StringIO

from app.application.ports.organization import OrganizationStore
from app.application.services.function_csv import _identity
from app.domain.organization.models import Employee, EmployeeFunction
from app.domain.organization.rules import normalize_employee


@dataclass(frozen=True)
class EmployeeImportResult:
    """Counts describing the committed employee import."""

    created: int
    updated: int
    deleted: int


def _assignments(value: str) -> list[EmployeeFunction]:
    """Decode the function assignments emitted by employee CSV export."""
    try:
        values = json.loads(value or '[]')
        if not isinstance(values, list):
            raise ValueError('Expected a JSON array.')
        result = []
        for item in values:
            if not isinstance(item, dict) or set(item) != {'function_id', 'allocation_pct'}:
                raise ValueError('Each assignment needs function_id and allocation_pct.')
            if type(item['function_id']) is not int or type(item['allocation_pct']) not in (int, float):
                raise ValueError('Function IDs and percentages must be numbers.')
            result.append(EmployeeFunction(item['function_id'], float(item['allocation_pct'])))
        return result
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f'Invalid function_assignments: {error}') from error


def parse_employees(content: bytes) -> list[Employee]:
    """Parse UTF-8 comma/semicolon CSV with explicit row and field errors."""
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise ValueError('The CSV must use UTF-8 encoding.') from error
    reader = csv.DictReader(StringIO(text, newline=''), strict=True,
                            delimiter=';' if ';' in text.partition('\n')[0] else ',')
    result, seen = [], set()
    try:
        columns = reader.fieldnames or []
        if not {'firstname', 'lastname', 'email'} <= set(columns) or len(set(columns)) != len(columns):
            raise ValueError('The CSV requires unique headers including firstname, lastname and email.')
        unknown = set(columns) - {field.name for field in fields(Employee)}
        if unknown:
            raise ValueError('Unsupported CSV columns: ' + ', '.join(sorted(unknown)))
        for number, row in enumerate(reader, 2):
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError('The number of values does not match the header.')
                row = {key: value.strip() for key, value in row.items()}
                deleted = row.get('deleted_flag', '').lower() or 'false'
                if deleted not in {'true', 'false', '0', '1'}:
                    raise ValueError('deleted_flag must be true or false.')
                identity = _identity(row.get('employee_id', ''), 'employee_id')
                if identity is not None and identity in seen:
                    raise ValueError(f'Duplicate employee_id {identity}.')
                seen.add(identity)
                try:
                    occupation = float(row.get('occupation_percentage') or '100')
                except ValueError as error:
                    raise ValueError('occupation_percentage must be a number between 0 and 100.') from error
                employee = Employee(**{key: _profile_text(row.get(key, '')) for key in
                    ('firstname', 'lastname', 'email', 'mobile', 'landline', 'sigle')},
                    employee_id=identity, occupation_percentage=occupation,
                    function_id=_identity(row.get('function_id', ''), 'function_id'),
                    function_assignments=_assignments(row['function_assignments']) if row.get('function_assignments') else None,
                    deleted_flag=deleted in {'true', '1'})
                result.append(normalize_employee(employee))
            except ValueError as error:
                raise ValueError(f'Row {number}: {error}') from error
    except csv.Error as error:
        raise ValueError(f'Invalid CSV near line {reader.line_num}: {error}. Check quotes and separators.') from error
    if not result:
        raise ValueError('The CSV contains no employee records.')
    return result


def _profile_text(value: str) -> str:
    """Reverse the spreadsheet formula guard added by our CSV exporter."""
    return value[1:] if len(value) > 1 and value[0] == "'" and value[1] in '=+-@\t\r\n' else value


def import_employees(store: OrganizationStore, employees: list[Employee], *, delete_missing: bool,
                     validate: Callable[[OrganizationStore, Employee], None]) -> EmployeeImportResult:
    """Upsert profiles and optional assignments within the caller's transaction."""
    existing = {item.employee_id: item for item in store.get_all_employees(include_deleted=True)}
    created = updated = 0
    included: set[int] = set()
    for number, employee in enumerate(employees, 2):
        try:
            previous = existing.get(employee.employee_id)
            if previous and employee.function_assignments is None and employee.function_id is None:
                employee = replace(employee, function_assignments=previous.assignments())
            validate(store, employee)
            if store.check_email_exists(employee.email, previous.employee_id if previous else None):
                raise ValueError('email is already used by another employee, including deleted employees.')
            if previous:
                identity = previous.employee_id
                updated += 1
            else:
                identity = store.create_employee(replace(employee, employee_id=None))
                created += 1
            store.write_imported_employee(replace(employee, employee_id=identity))
            included.add(identity)
        except ValueError as error:
            raise ValueError(f'Row {number}, employee "{employee.firstname} {employee.lastname}": {error}') from error
    omitted = [identity for identity, item in existing.items()
               if delete_missing and identity not in included and not item.deleted_flag]
    for identity in omitted:
        store.delete_employee(identity)
    return EmployeeImportResult(created, updated, len(omitted))
