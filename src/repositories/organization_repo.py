"""Compatibility facade preserving organization DataFrames and SQLite errors."""

from contextlib import contextmanager
from collections.abc import Iterator
from datetime import date
import sqlite3

import pandas as pd

from app.application.exceptions import OrganizationConflictError, OrganizationStorageError
from app.domain.organization.models import Employee, EmployeeCalendarException, FunctionType, OrgFunction, Team
from app.main import create_organization_service
from app.presentation.components.organization_frames import (
    employees_frame, exceptions_frame, function_types_frame, functions_frame, teams_frame,
)


@contextmanager
def legacy_organization_errors() -> Iterator[None]:
    """Restore the database exception contracts expected by legacy callers."""
    try:
        yield
    except (OrganizationConflictError, OrganizationStorageError) as exc:
        if isinstance(exc.__cause__, sqlite3.DatabaseError):
            raise exc.__cause__ from exc
        raise


class OrganizationRepository:
    """Adapt legacy callers to the organization application service."""

    def __init__(self, db_path: str | None = None) -> None:
        """Retain the database path and construct the application dependency."""
        self.db_path = db_path
        self.service = create_organization_service(db_path)

    def get_all_function_types(self) -> pd.DataFrame:
        """Get all function types using the migrated service."""
        with legacy_organization_errors():
            return function_types_frame(self.service.get_all_function_types())

    def get_function_type_by_id(self, type_id: int) -> FunctionType | None:
        """Get function type by id using the migrated service."""
        with legacy_organization_errors():
            return self.service.get_function_type_by_id(type_id)

    def create_function_type(self, ftype: FunctionType) -> int:
        """Create function type using the migrated service."""
        with legacy_organization_errors():
            return self.service.create_function_type(ftype)

    def update_function_type(self, ftype: FunctionType) -> bool:
        """Update function type using the migrated service."""
        with legacy_organization_errors():
            return self.service.update_function_type(ftype)

    def delete_function_type(self, type_id: int) -> bool:
        """Delete function type using the migrated service."""
        with legacy_organization_errors():
            return self.service.delete_function_type(type_id)

    def get_all_functions(self) -> pd.DataFrame:
        """Get all functions using the migrated service."""
        with legacy_organization_errors():
            frame = functions_frame(self.service.get_all_functions())
            frame["has_reports"] = frame["has_reports"].astype(int)
            return frame

    def get_function_by_id(self, func_id: int) -> OrgFunction | None:
        """Get function by id using the migrated service."""
        with legacy_organization_errors():
            return self.service.get_function_by_id(func_id)

    def create_function(self, func: OrgFunction) -> int:
        """Create function using the migrated service."""
        with legacy_organization_errors():
            return self.service.create_function(func)

    def update_function(self, func: OrgFunction) -> bool:
        """Update function using the migrated service."""
        with legacy_organization_errors():
            return self.service.update_function(func)

    def delete_function(self, func_id: int) -> bool:
        """Delete function using the migrated service."""
        with legacy_organization_errors():
            return self.service.delete_function(func_id)

    def get_all_teams(self) -> pd.DataFrame:
        """Get all teams using the migrated service."""
        with legacy_organization_errors():
            return teams_frame(self.service.get_all_teams())

    def get_team_by_id(self, team_id: int) -> Team | None:
        """Get team by id using the migrated service."""
        with legacy_organization_errors():
            return self.service.get_team_by_id(team_id)

    def create_team(self, team: Team) -> int:
        """Create team using the migrated service."""
        with legacy_organization_errors():
            return self.service.create_team(team)

    def update_team(self, team: Team) -> bool:
        """Update team using the migrated service."""
        with legacy_organization_errors():
            return self.service.update_team(team)

    def delete_team(self, team_id: int) -> bool:
        """Delete team using the migrated service."""
        with legacy_organization_errors():
            return self.service.delete_team(team_id)

    def get_all_employees(self) -> pd.DataFrame:
        """Get all employees using the migrated service."""
        with legacy_organization_errors():
            return employees_frame(self.service.get_all_employees())

    def get_employee_by_id(self, emp_id: int) -> Employee | None:
        """Get employee by id using the migrated service."""
        with legacy_organization_errors():
            return self.service.get_employee_by_id(emp_id)

    def create_employee(self, emp: Employee) -> int:
        """Create employee using the migrated service."""
        with legacy_organization_errors():
            return self.service.create_employee(emp)

    def update_employee(self, emp: Employee) -> bool:
        """Update employee using the migrated service."""
        with legacy_organization_errors():
            return self.service.update_employee(emp)

    def delete_employee(self, emp_id: int) -> bool:
        """Delete employee using the migrated service."""
        with legacy_organization_errors():
            return self.service.delete_employee(emp_id)

    def get_employee_calendar_exceptions(self, emp_id: int | None = None) -> pd.DataFrame:
        """Get employee calendar exceptions using the migrated service."""
        with legacy_organization_errors():
            return exceptions_frame(self.service.get_employee_calendar_exceptions(emp_id))

    def get_employee_calendar_exception_by_id(self, exception_id: int) -> EmployeeCalendarException | None:
        """Get employee calendar exception by id using the migrated service."""
        with legacy_organization_errors():
            return self.service.get_employee_calendar_exception_by_id(exception_id)

    def has_overlapping_calendar_exception(self, employee_id: int, start_date: date, end_date: date, exclude_id: int | None = None) -> bool:
        """Has overlapping calendar exception using the migrated service."""
        with legacy_organization_errors():
            return self.service.has_overlapping_calendar_exception(employee_id, start_date, end_date, exclude_id)

    def create_employee_calendar_exception(self, exception: EmployeeCalendarException) -> int:
        """Create employee calendar exception using the migrated service."""
        with legacy_organization_errors():
            return self.service.create_employee_calendar_exception(exception)

    def update_employee_calendar_exception(self, exception: EmployeeCalendarException) -> bool:
        """Update employee calendar exception using the migrated service."""
        with legacy_organization_errors():
            return self.service.update_employee_calendar_exception(exception)

    def delete_employee_calendar_exception(self, exception_id: int) -> bool:
        """Delete employee calendar exception using the migrated service."""
        with legacy_organization_errors():
            return self.service.delete_employee_calendar_exception(exception_id)

    def get_effective_occupation_percentage(self, employee_id: int, on_date: date) -> float | None:
        """Get effective occupation percentage using the migrated service."""
        with legacy_organization_errors():
            return self.service.get_effective_occupation_percentage(employee_id, on_date)

    def check_email_exists(self, email: str, exclude_id: int | None = None) -> bool:
        """Check email exists using the migrated service."""
        with legacy_organization_errors():
            return self.service.check_email_exists(email, exclude_id)

    def check_code_exists(self, code: str, exclude_id: int | None = None) -> bool:
        """Check code exists using the migrated service."""
        with legacy_organization_errors():
            return self.service.check_code_exists(code, exclude_id)

    def generate_next_employee_code(self) -> str:
        """Generate next employee code using the migrated service."""
        with legacy_organization_errors():
            return self.service.generate_next_employee_code()
