"""Organization use cases, validation, and atomic multi-record changes."""

import csv
import io
from dataclasses import fields, replace
from datetime import date

from app.application.ports.organization import CalendarExceptionRow, OrganizationGateway, OrganizationStore
from app.application.ports.references import EmployeeReference, FunctionReference
from app.domain.access.models import Permission
from app.domain.hierarchy import HierarchyType, normalize_hierarchy_type, validate_hierarchy_type_id
from app.domain.organization.models import Employee, EmployeeCalendarException, FunctionType, OrgFunction, Team
from app.domain.organization.rules import (
    next_employee_code, normalize_employee, normalize_exception, normalize_function,
    normalize_function_type, normalize_team, validate_team_parent,
)


class OrganizationService:
    """Apply organization rules through an injected transaction provider."""

    def __init__(self, gateway: OrganizationGateway) -> None:
        """Inject persistence without acquiring a connection."""
        self._gateway = gateway

    def function_references(self) -> list[FunctionReference]:
        """Read only names and reporting ancestry for project manager labels."""
        return self._gateway.run(lambda store: store.function_references())

    def employee_references(self) -> list[EmployeeReference]:
        """Read occupant names without personal contact or staffing information."""
        return self._gateway.run(lambda store: store.employee_references())

    def get_all_function_types(self) -> list[FunctionType]:
        """Get all function types within one organization transaction."""
        return self._gateway.run(lambda store: store.get_all_function_types(), permission=Permission.SHARED)

    def get_all_hierarchy_types(self) -> list[HierarchyType]:
        """Read the shared classification catalog with all localized labels."""
        return self._gateway.run(lambda store: store.get_all_hierarchy_types(), permission=Permission.SHARED)

    def save_hierarchy_type(self, value: HierarchyType) -> int:
        """Create a type or edit its labels while keeping its code stable."""
        value = normalize_hierarchy_type(value)
        validate_hierarchy_type_id(value.id)
        return self._gateway.run(lambda store: store.save_hierarchy_type(value), write=True, permission=Permission.SHARED)

    def delete_hierarchy_type(self, type_id: int) -> bool:
        """Soft-delete a classification only when no records reference it."""
        validate_hierarchy_type_id(type_id)
        def operation(store: OrganizationStore) -> bool:
            if store.hierarchy_type_in_use(type_id):
                raise ValueError("This hierarchy type is in use and cannot be deleted.")
            return store.delete_hierarchy_type(type_id)
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def get_function_type_by_id(self, type_id: int) -> FunctionType | None:
        """Get function type by id within one organization transaction."""
        return self._gateway.run(lambda store: store.get_function_type_by_id(type_id), permission=Permission.SHARED)

    def create_function_type(self, ftype: FunctionType) -> int:
        """Create function type within one organization transaction."""
        ftype = normalize_function_type(ftype)
        return self._gateway.run(lambda store: store.create_function_type(ftype), write=True, permission=Permission.SHARED)

    def update_function_type(self, ftype: FunctionType) -> bool:
        """Update function type within one organization transaction."""
        if ftype.function_type_id is None:
            return False
        ftype = normalize_function_type(ftype)
        return self._gateway.run(lambda store: store.update_function_type(ftype), write=True, permission=Permission.SHARED)

    def delete_function_type(self, type_id: int) -> bool:
        """Soft-delete a function type only when no functions reference it."""
        def operation(store: OrganizationStore) -> bool:
            if store.function_type_in_use(type_id):
                raise ValueError("This function type is in use and cannot be deleted.")
            return store.delete_function_type(type_id)
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def get_all_functions(self) -> list[OrgFunction]:
        """Get all functions within one organization transaction."""
        return self._gateway.run(lambda store: store.get_all_functions(), permission=Permission.SHARED)

    def get_function_by_id(self, func_id: int) -> OrgFunction | None:
        """Get function by id within one organization transaction."""
        return self._gateway.run(lambda store: store.get_function_by_id(func_id), permission=Permission.SHARED)

    def create_function(self, func: OrgFunction) -> int:
        """Create function within one organization transaction."""
        func = normalize_function(func)
        return self._gateway.run(lambda store: store.create_function(func), write=True, permission=Permission.SHARED)

    def update_function(self, func: OrgFunction) -> bool:
        """Update function within one organization transaction."""
        if func.function_id is None:
            return False
        func = normalize_function(func)
        return self._gateway.run(lambda store: store.update_function(func), write=True, permission=Permission.SHARED)

    def delete_function(self, func_id: int) -> bool:
        """Delete function within one organization transaction."""
        return self._gateway.run(lambda store: store.delete_function(func_id), write=True, permission=Permission.SHARED)

    def get_all_teams(self) -> list[Team]:
        """Get all teams within one organization transaction."""
        return self._gateway.run(lambda store: store.get_all_teams(), permission=Permission.SHARED)

    def export_csv(self, catalog: str) -> str:
        """Export a complete organization catalog after checking shared-data access.

        Args:
            catalog: One of functions, function_types, teams, or employees.

        Returns:
            Comma-separated UTF-8 text with stable field names and escaped cells.

        Raises:
            ValueError: The catalog name is unsupported.
        """
        def operation(store: OrganizationStore) -> str:
            catalogs = {
                'functions': (OrgFunction, store.get_all_functions),
                'function_types': (FunctionType, store.get_all_function_types),
                'teams': (Team, store.get_all_teams),
                'employees': (Employee, store.get_all_employees),
            }
            if catalog not in catalogs:
                raise ValueError('Unknown organization catalog.')
            model, read = catalogs[catalog]
            columns = [field.name for field in fields(model)]
            output = io.StringIO(newline='')
            writer = csv.writer(output, lineterminator='\r\n')
            writer.writerow(columns)
            for record in read():
                values = [getattr(record, column) for column in columns]
                writer.writerow([
                    "'" + value if isinstance(value, str) and value.startswith(
                        ('=', '+', '-', '@', '\t', '\r', '\n')) else value
                    for value in values
                ])
            return output.getvalue()

        return self._gateway.run(operation, permission=Permission.SHARED)

    def get_team_by_id(self, team_id: int) -> Team | None:
        """Get team by id within one organization transaction."""
        return self._gateway.run(lambda store: store.get_team_by_id(team_id), permission=Permission.SHARED)

    def create_team(self, team: Team, *, function_ids: list[int] | None = None) -> int:
        """Create team within one organization transaction."""
        team = normalize_team(team)
        function_ids = list(function_ids) if function_ids is not None else None
        def operation(store: OrganizationStore) -> int:
            if team.parent_team_id is not None:
                validate_team_parent(team, store.get_all_teams())
            result = store.create_team(team)
            if result and function_ids is not None:
                store.set_team_functions(result, function_ids)
            return result
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def update_team(self, team: Team, *, function_ids: list[int] | None = None) -> bool:
        """Update team within one organization transaction."""
        if team.team_id is None:
            return False
        team = normalize_team(team)
        function_ids = list(function_ids) if function_ids is not None else None
        def operation(store: OrganizationStore) -> bool:
            if team.parent_team_id is not None:
                validate_team_parent(team, store.get_all_teams())
            result = store.update_team(team)
            if result and function_ids is not None:
                store.set_team_functions(team.team_id, function_ids)
            return result
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def delete_team(self, team_id: int) -> bool:
        """Soft-delete a team after its active children have been moved or deleted."""
        def operation(store: OrganizationStore) -> bool:
            if any(team.parent_team_id == team_id for team in store.get_all_teams()):
                raise ValueError("Move or delete this team's children before deleting the team.")
            return store.delete_team(team_id)
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def get_all_employees(self) -> list[Employee]:
        """Get all employees within one organization transaction."""
        return self._gateway.run(lambda store: store.get_all_employees(), permission=Permission.SHARED)

    def get_employee_by_id(self, emp_id: int) -> Employee | None:
        """Get employee by id within one organization transaction."""
        return self._gateway.run(lambda store: store.get_employee_by_id(emp_id), permission=Permission.SHARED)

    def create_employee(self, emp: Employee, *, initial_exception: EmployeeCalendarException | None = None) -> int:
        """Create employee within one organization transaction."""
        emp = normalize_employee(emp)
        initial_exception = replace(initial_exception) if initial_exception is not None else None
        def operation(store: OrganizationStore) -> int:
            employee_id = store.create_employee(emp)
            if initial_exception is not None:
                exception = normalize_exception(replace(initial_exception, employee_id=employee_id, exception_id=None))
                store.create_employee_calendar_exception(exception)
            return employee_id
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def update_employee(self, emp: Employee) -> bool:
        """Update employee within one organization transaction."""
        if emp.employee_id is None:
            return False
        emp = normalize_employee(emp)
        return self._gateway.run(lambda store: store.update_employee(emp), write=True, permission=Permission.SHARED)

    def delete_employee(self, emp_id: int) -> bool:
        """Delete employee within one organization transaction."""
        return self._gateway.run(lambda store: store.delete_employee(emp_id), write=True, permission=Permission.SHARED)

    def get_employee_calendar_exceptions(self, emp_id: int | None = None) -> list[CalendarExceptionRow]:
        """Get employee calendar exceptions within one organization transaction."""
        return self._gateway.run(lambda store: store.get_employee_calendar_exceptions(emp_id), permission=Permission.SHARED)

    def get_employee_calendar_exception_by_id(self, exception_id: int) -> EmployeeCalendarException | None:
        """Get employee calendar exception by id within one organization transaction."""
        return self._gateway.run(lambda store: store.get_employee_calendar_exception_by_id(exception_id), permission=Permission.SHARED)

    def has_overlapping_calendar_exception(self, employee_id: int, start_date: date, end_date: date, exclude_id: int | None = None) -> bool:
        """Has overlapping calendar exception within one organization transaction."""
        return self._gateway.run(lambda store: store.has_overlapping_calendar_exception(employee_id, start_date, end_date, exclude_id), permission=Permission.SHARED)

    def create_employee_calendar_exception(self, exception: EmployeeCalendarException) -> int:
        """Create employee calendar exception within one organization transaction."""
        exception = normalize_exception(exception)
        def operation(store: OrganizationStore) -> int:
            if store.has_overlapping_calendar_exception(
                exception.employee_id, exception.start_date, exception.end_date, None,
            ):
                raise ValueError("This period overlaps an existing calendar exception for the employee.")
            return store.create_employee_calendar_exception(exception)
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def update_employee_calendar_exception(self, exception: EmployeeCalendarException) -> bool:
        """Update employee calendar exception within one organization transaction."""
        if exception.exception_id is None:
            return False
        exception = normalize_exception(exception)
        def operation(store: OrganizationStore) -> bool:
            if store.has_overlapping_calendar_exception(
                exception.employee_id, exception.start_date, exception.end_date, exception.exception_id,
            ):
                raise ValueError("This period overlaps an existing calendar exception for the employee.")
            return store.update_employee_calendar_exception(exception)
        return self._gateway.run(operation, write=True, permission=Permission.SHARED)

    def delete_employee_calendar_exception(self, exception_id: int) -> bool:
        """Delete employee calendar exception within one organization transaction."""
        return self._gateway.run(lambda store: store.delete_employee_calendar_exception(exception_id), write=True, permission=Permission.SHARED)

    def get_effective_occupation_percentage(self, employee_id: int, on_date: date) -> float | None:
        """Get effective occupation percentage within one organization transaction."""
        return self._gateway.run(lambda store: store.get_effective_occupation_percentage(employee_id, on_date), permission=Permission.SHARED)

    def check_email_exists(self, email: str, exclude_id: int | None = None) -> bool:
        """Check email exists within one organization transaction."""
        return self._gateway.run(lambda store: store.check_email_exists(email, exclude_id), permission=Permission.SHARED)

    def check_code_exists(self, code: str, exclude_id: int | None = None) -> bool:
        """Check code exists within one organization transaction."""
        return self._gateway.run(lambda store: store.check_code_exists(code, exclude_id), permission=Permission.SHARED)

    def generate_next_employee_code(self) -> str:
        """Preview the next code; uniqueness is enforced again when saving."""
        return self._gateway.run(lambda store: next_employee_code(store.employee_codes()), permission=Permission.SHARED)

    def get_team_functions(self, team_id: int) -> list[int]:
        """Get team functions in a single transaction."""
        return self._gateway.run(lambda store: store.get_team_functions(team_id), permission=Permission.SHARED)

    def set_team_functions(self, team_id: int, function_ids: list[int]) -> None:
        """Set team functions in a single transaction."""
        function_ids = list(function_ids)
        return self._gateway.run(lambda store: store.set_team_functions(team_id, function_ids), write=True, permission=Permission.SHARED)

    def add_team_function(self, team_id: int, function_id: int) -> bool:
        """Add team function in a single transaction."""
        return self._gateway.run(lambda store: store.add_team_function(team_id, function_id), write=True, permission=Permission.SHARED)

    def remove_team_function(self, team_id: int, function_id: int) -> bool:
        """Remove team function in a single transaction."""
        return self._gateway.run(lambda store: store.remove_team_function(team_id, function_id), write=True, permission=Permission.SHARED)
