"""Organization use cases, validation, and atomic multi-record changes."""

from app.domain.access.models import Permission
from app.application.ports.references import EmployeeReference, FunctionReference


from dataclasses import replace
from datetime import date

from app.application.ports.organization import CalendarExceptionRow, OrganizationGateway
from app.domain.organization.models import Employee, EmployeeCalendarException, FunctionType, OrgFunction, Team
from app.domain.organization.rules import (
    next_employee_code, normalize_employee, normalize_exception, normalize_function,
    normalize_function_type, normalize_team,
)


class OrganizationService:
    """Apply organization rules through an injected transaction provider."""

    def __init__(self, gateway: OrganizationGateway) -> None:
        """Inject persistence without acquiring a connection."""
        self._gateway = gateway

    def function_references(self) -> list[FunctionReference]:
        """Read only names and reporting ancestry for project manager labels."""
        with self._gateway.transaction() as store:
            return [FunctionReference(row.function_id, row.name, row.hierarchy_level,
                                      row.manager_function_id) for row in store.get_all_functions()]

    def employee_references(self) -> list[EmployeeReference]:
        """Read occupant names without personal contact or staffing information."""
        with self._gateway.transaction() as store:
            return [EmployeeReference(row.function_id, row.firstname, row.lastname)
                    for row in store.get_all_employees()]

    def get_all_function_types(self) -> list[FunctionType]:
        """Get all function types within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.get_all_function_types()

    def get_function_type_by_id(self, type_id: int) -> FunctionType | None:
        """Get function type by id within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.get_function_type_by_id(type_id)

    def create_function_type(self, ftype: FunctionType) -> int:
        """Create function type within one organization transaction."""
        ftype = normalize_function_type(ftype)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.create_function_type(ftype)

    def update_function_type(self, ftype: FunctionType) -> bool:
        """Update function type within one organization transaction."""
        if ftype.function_type_id is None:
            return False
        ftype = normalize_function_type(ftype)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.update_function_type(ftype)

    def delete_function_type(self, type_id: int) -> bool:
        """Delete function type within one organization transaction."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.delete_function_type(type_id)

    def get_all_functions(self) -> list[OrgFunction]:
        """Get all functions within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.get_all_functions()

    def get_function_by_id(self, func_id: int) -> OrgFunction | None:
        """Get function by id within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.get_function_by_id(func_id)

    def create_function(self, func: OrgFunction) -> int:
        """Create function within one organization transaction."""
        func = normalize_function(func)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.create_function(func)

    def update_function(self, func: OrgFunction) -> bool:
        """Update function within one organization transaction."""
        if func.function_id is None:
            return False
        func = normalize_function(func)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.update_function(func)

    def delete_function(self, func_id: int) -> bool:
        """Delete function within one organization transaction."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.delete_function(func_id)

    def get_all_teams(self) -> list[Team]:
        """Get all teams within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.get_all_teams()

    def get_team_by_id(self, team_id: int) -> Team | None:
        """Get team by id within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.get_team_by_id(team_id)

    def create_team(self, team: Team, *, function_ids: list[int] | None = None) -> int:
        """Create team within one organization transaction."""
        team = normalize_team(team)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            result = store.create_team(team)
            if result and function_ids is not None:
                store.set_team_functions(result, function_ids)
            return result

    def update_team(self, team: Team, *, function_ids: list[int] | None = None) -> bool:
        """Update team within one organization transaction."""
        if team.team_id is None:
            return False
        team = normalize_team(team)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            result = store.update_team(team)
            if result and function_ids is not None:
                store.set_team_functions(team.team_id, function_ids)
            return result

    def delete_team(self, team_id: int) -> bool:
        """Delete team within one organization transaction."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.delete_team(team_id)

    def get_all_employees(self) -> list[Employee]:
        """Get all employees within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.get_all_employees()

    def get_employee_by_id(self, emp_id: int) -> Employee | None:
        """Get employee by id within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.get_employee_by_id(emp_id)

    def create_employee(self, emp: Employee, *, initial_exception: EmployeeCalendarException | None = None) -> int:
        """Create employee within one organization transaction."""
        emp = normalize_employee(emp)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            employee_id = store.create_employee(emp)
            if initial_exception is not None:
                exception = normalize_exception(replace(initial_exception, employee_id=employee_id, exception_id=None))
                store.create_employee_calendar_exception(exception)
            return employee_id

    def update_employee(self, emp: Employee) -> bool:
        """Update employee within one organization transaction."""
        if emp.employee_id is None:
            return False
        emp = normalize_employee(emp)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.update_employee(emp)

    def delete_employee(self, emp_id: int) -> bool:
        """Delete employee within one organization transaction."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.delete_employee(emp_id)

    def get_employee_calendar_exceptions(self, emp_id: int | None = None) -> list[CalendarExceptionRow]:
        """Get employee calendar exceptions within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.get_employee_calendar_exceptions(emp_id)

    def get_employee_calendar_exception_by_id(self, exception_id: int) -> EmployeeCalendarException | None:
        """Get employee calendar exception by id within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.get_employee_calendar_exception_by_id(exception_id)

    def has_overlapping_calendar_exception(self, employee_id: int, start_date: date, end_date: date, exclude_id: int | None = None) -> bool:
        """Has overlapping calendar exception within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.has_overlapping_calendar_exception(employee_id, start_date, end_date, exclude_id)

    def create_employee_calendar_exception(self, exception: EmployeeCalendarException) -> int:
        """Create employee calendar exception within one organization transaction."""
        exception = normalize_exception(exception)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            if store.has_overlapping_calendar_exception(
                exception.employee_id, exception.start_date, exception.end_date, None,
            ):
                raise ValueError("This period overlaps an existing calendar exception for the employee.")
            return store.create_employee_calendar_exception(exception)

    def update_employee_calendar_exception(self, exception: EmployeeCalendarException) -> bool:
        """Update employee calendar exception within one organization transaction."""
        if exception.exception_id is None:
            return False
        exception = normalize_exception(exception)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            if store.has_overlapping_calendar_exception(
                exception.employee_id, exception.start_date, exception.end_date, exception.exception_id,
            ):
                raise ValueError("This period overlaps an existing calendar exception for the employee.")
            return store.update_employee_calendar_exception(exception)

    def delete_employee_calendar_exception(self, exception_id: int) -> bool:
        """Delete employee calendar exception within one organization transaction."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.delete_employee_calendar_exception(exception_id)

    def get_effective_occupation_percentage(self, employee_id: int, on_date: date) -> float | None:
        """Get effective occupation percentage within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.get_effective_occupation_percentage(employee_id, on_date)

    def check_email_exists(self, email: str, exclude_id: int | None = None) -> bool:
        """Check email exists within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.check_email_exists(email, exclude_id)

    def check_code_exists(self, code: str, exclude_id: int | None = None) -> bool:
        """Check code exists within one organization transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.check_code_exists(code, exclude_id)

    def generate_next_employee_code(self) -> str:
        """Preview the next code; uniqueness is enforced again when saving."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return next_employee_code(store.employee_codes())

    def get_team_functions(self, team_id: int) -> list[int]:
        """Get team functions in a single transaction."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.get_team_functions(team_id)

    def set_team_functions(self, team_id: int, function_ids: list[int]) -> None:
        """Set team functions in a single transaction."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.set_team_functions(team_id, function_ids)

    def add_team_function(self, team_id: int, function_id: int) -> bool:
        """Add team function in a single transaction."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.add_team_function(team_id, function_id)

    def remove_team_function(self, team_id: int, function_id: int) -> bool:
        """Remove team function in a single transaction."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.remove_team_function(team_id, function_id)
