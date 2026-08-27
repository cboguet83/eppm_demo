"""Organizational functions, function types, teams, and employee models."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class FunctionType:
    """Represents a category of organizational function.

    Attributes:
        function_type_id: Unique primary key identifier.
        function_type: Name/label of function type (e.g. 'Executive', 'Operational').
    """

    function_type: str
    function_type_id: Optional[int] = None


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
    function_id: Optional[int] = None
    function_type_id: Optional[int] = None
    manager_function_id: Optional[int] = None
    dual_manager_function_id: Optional[int] = None
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
    team_id: Optional[int] = None
    manager_function_id: Optional[int] = None
    leader_function_id: Optional[int] = None


@dataclass
class Employee:
    """Represents an employee / team member record.

    Attributes:
        employee_id: Unique primary key identifier.
        firstname: First / given name.
        lastname: Last / family name.
        email: Work email address (must be unique).
        mobile: Contact telephone or mobile number.
        sigle: Trigram / initials acronym (e.g. 'JDO', 'ASM').
        employee_code: Unique employee badge/code (e.g. 'EMP-001').
        function_id: Associated function role ID.
    """

    firstname: str
    lastname: str
    email: str
    employee_code: str
    employee_id: Optional[int] = None
    mobile: str = ""
    sigle: str = ""
    function_id: Optional[int] = None
