"""Pure organization validation and normalization, independent of storage."""

from collections.abc import Iterable
from dataclasses import replace
from datetime import date
from math import isfinite
import re

from app.domain.hierarchy import validate_hierarchy_type_id
from app.domain.organization.models import (
    Employee, EmployeeCalendarException, FunctionHierarchy, FunctionType, OrgFunction, Team,
)

EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")

def is_valid_email(email: str) -> bool:
    """Validates standard email format.

    Args:
        email: Email address string to test.

    Returns:
        bool: True if valid email format.
    """
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_REGEX.match(email.strip()))


def validate_function(name: str, hierarchy_level: int | None, fte_percentage: int = 100) -> None:
    """Validates job function fields.

    Args:
        name: Function title.
        hierarchy_level: Numerical hierarchy level rank (must be >= 1).
        fte_percentage: FTE workload percentage.

    Raises:
        ValueError: If validation fails.
    """
    if not name or not name.strip():
        raise ValueError("Function name cannot be empty.")
    if type(hierarchy_level) is not int or hierarchy_level < 1:
        raise ValueError("Hierarchy level must be an integer greater than or equal to 1.")
    if not isfinite(fte_percentage) or not 0 <= fte_percentage <= 100:
        raise ValueError("FTE percentage must be between 0 and 100.")


def validate_team(team_name: str) -> None:
    """Validates team fields.

    Args:
        team_name: Team name.

    Raises:
        ValueError: If validation fails.
    """
    if not team_name or not team_name.strip():
        raise ValueError("Team name cannot be empty.")


def validate_employee(
    firstname: str,
    lastname: str,
    email: str,
    employee_code: str,
    occupation_percentage: float = 100.0,
) -> None:
    """Validates employee profile fields.

    Args:
        firstname: First name.
        lastname: Last name.
        email: Email address.
        employee_code: Unique badge code.
        occupation_percentage: Normal working percentage from 0 to 100.

    Raises:
        ValueError: If validation fails.
    """
    if not firstname or not firstname.strip():
        raise ValueError("First name cannot be empty.")
    if not lastname or not lastname.strip():
        raise ValueError("Last name cannot be empty.")
    if not email or not is_valid_email(email):
        raise ValueError(f"Invalid email address: '{email}'.")
    if not employee_code or not employee_code.strip():
        raise ValueError("Employee code cannot be empty.")
    validate_occupation_percentage(occupation_percentage)


def validate_occupation_percentage(occupation_percentage: float) -> None:
    """Validates a normal or exceptional occupation percentage."""
    if not isfinite(occupation_percentage) or not 0 <= occupation_percentage <= 100:
        raise ValueError("Occupation percentage must be between 0 and 100.")


def validate_employee_calendar_exception(
    start_date: date,
    end_date: date,
    occupation_percentage: float,
) -> None:
    """Validates an inclusive, date-bounded occupation override."""
    if start_date is None or end_date is None:
        raise ValueError("Both start and end dates are required.")
    if end_date < start_date:
        raise ValueError("End date must be on or after start date.")
    validate_occupation_percentage(occupation_percentage)


def normalize_function_type(value: FunctionType) -> FunctionType:
    """Require a nonblank function-type name and trim surrounding whitespace."""
    if not value.function_type.strip():
        raise ValueError("Function type name cannot be empty.")
    return replace(value, function_type=value.function_type.strip())


def normalize_function(value: OrgFunction) -> OrgFunction:
    """Validate a function while retaining legacy multi-FTE capacity values.

    The editor limits input to 100%; existing capacity integrations also store
    functions representing more than one FTE, which remain supported.
    """
    fte = value.fte_percentage if value.fte_percentage is not None else 100
    validate_function(value.name, value.hierarchy_level)
    if not isfinite(fte) or fte < 0:
        raise ValueError("FTE percentage must be finite and nonnegative.")
    return replace(value, name=value.name.strip(), fte_percentage=fte)


def normalize_team(value: Team) -> Team:
    """Validate and trim a team name without changing its references."""
    validate_hierarchy_type_id(value.hierarchy_type_id)
    validate_team(value.team_name)
    return replace(value, team_name=value.team_name.strip())


def normalize_employee(value: Employee) -> Employee:
    """Validate profiles and preserve case normalization of codes and email."""
    validate_employee(value.firstname, value.lastname, value.email,
                      value.employee_code, value.occupation_percentage)
    return replace(value, firstname=value.firstname.strip(), lastname=value.lastname.strip(),
                   email=value.email.strip().lower(), mobile=value.mobile.strip(),
                   landline=value.landline.strip(),
                   sigle=value.sigle.strip().upper(), employee_code=value.employee_code.strip().upper())


def normalize_exception(value: EmployeeCalendarException) -> EmployeeCalendarException:
    """Validate inclusive calendar boundaries and trim the optional reason."""
    validate_employee_calendar_exception(value.start_date, value.end_date, value.occupation_percentage)
    return replace(value, reason=value.reason.strip())


def next_employee_code(codes: Iterable[str]) -> str:
    """Suggest the next EMP code, retaining the historical suffix interpretation."""
    existing = set(codes)
    maximum = 0
    for code in existing:
        parts = code.split("-")
        if code.startswith("EMP-") and parts[1].isdecimal():
            maximum = max(maximum, int(parts[1]))
    candidate = maximum + 1
    occupied = {code.upper() for code in existing}
    while f"EMP-{candidate:03d}" in occupied:
        candidate += 1
    return f"EMP-{candidate:03d}"


def find_level_3_function(
    function_id: int | None,
    func_lookup: dict[int, FunctionHierarchy],
) -> FunctionHierarchy | None:
    """Find the level-three ancestor, retaining the 20-hop limit and cycle guard."""
    curr_id: int | None = function_id
    visited: set[int] = set()
    max_depth = 20
    depth = 0

    while curr_id is not None and curr_id not in visited and depth < max_depth:
        visited.add(curr_id)
        depth += 1
        node = func_lookup.get(curr_id)
        if not node:
            break
        if node["hierarchy_level"] == 3:
            return node
        if node["hierarchy_level"] < 3:
            break
        curr_id = node["manager_function_id"]

    return None
