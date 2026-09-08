"""Compatibility exports for organization domain records."""

from app.domain.organization.models import (
    Employee, EmployeeCalendarException, FunctionType, OrgFunction, Team,
)

__all__ = ["Employee", "EmployeeCalendarException", "FunctionType", "OrgFunction", "Team"]
