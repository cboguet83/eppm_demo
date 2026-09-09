"""Organizational functions, function types, teams, and employee models."""

from dataclasses import dataclass
from datetime import date
from typing import TypedDict


@dataclass
class FunctionType:
    """Represents a category of organizational function.

    Attributes:
        function_type_id: Unique primary key identifier.
        function_type: Name/label of function type (e.g. 'Executive', 'Operational').
    """

    function_type: str
    function_type_id: int | None = None


@dataclass
class OrgFunction:
    """Represents a job function or organizational role.

    Attributes:
        name: Title of the function (e.g. 'Chief Technology Officer', 'Project Manager').
        hierarchy_level: Numerical hierarchy level rank (e.g. 1 for Executive, 2 for VP, etc.).
        function_id: Unique primary key identifier.
        function_type_id: Optional associated function type ID.
        manager_function_id: Direct reporting manager function ID.
        dual_manager_function_id: Optional secondary / dotted-line manager function ID.
        fte_percentage: Full-time equivalent workload percentage (default 100).
        has_reports: Whether this function has reporting subordinates (default False).
    """

    name: str
    hierarchy_level: int
    function_id: int | None = None
    function_type_id: int | None = None
    manager_function_id: int | None = None
    dual_manager_function_id: int | None = None
    fte_percentage: int = 100
    has_reports: bool = False


@dataclass
class Team:
    """Represents an organizational team.

    Attributes:
        team_name: Name of the team.
        team_id: Unique primary key identifier.
        manager_function_id: Optional manager function ID for the team.
        leader_function_id: Optional team leader function ID.
    """

    team_name: str
    team_id: int | None = None
    manager_function_id: int | None = None
    leader_function_id: int | None = None


@dataclass
class Employee:
    """Represents an employee / team member record.

    Attributes:
        employee_id: Unique primary key identifier.
        firstname: First / given name.
        lastname: Last / family name.
        email: Work email address (must be unique).
        mobile: Mobile telephone number.
        landline: Landline telephone number.
        sigle: Trigram / initials acronym (e.g. 'JDO', 'ASM').
        employee_code: Unique employee badge/code (e.g. 'EMP-001').
        function_id: Associated function role ID.
        occupation_percentage: Employee's normal working percentage (0 to 100).
    """

    firstname: str
    lastname: str
    email: str
    employee_code: str
    employee_id: int | None = None
    mobile: str = ""
    sigle: str = ""
    function_id: int | None = None
    occupation_percentage: float = 100.0
    landline: str = ""


@dataclass
class EmployeeCalendarException:
    """Represents a temporary override to an employee's occupation percentage.

    Date ranges are inclusive, so an exception from January 1 through January 31
    applies on both boundary dates.

    Attributes:
        employee_id: Employee whose normal occupation percentage is overridden.
        start_date: First date on which the override applies.
        end_date: Last date on which the override applies.
        occupation_percentage: Temporary working percentage (0 to 100).
        reason: Optional explanation, such as "Maternity leave".
        exception_id: Unique primary key identifier.
    """

    employee_id: int
    start_date: date
    end_date: date
    occupation_percentage: float
    reason: str = ""
    exception_id: int | None = None


class FunctionHierarchy(TypedDict):
    """Plain hierarchy node used by existing planning-label traversal."""

    function_id: int
    name: str
    hierarchy_level: int
    manager_function_id: int | None
