"""Organizational hierarchy, functions, function types, and employee models."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class HierarchyLevel:
    """Represents an organizational hierarchy tier.

    Attributes:
        hierarchy_level_id: Unique primary key identifier.
        name: Name of the hierarchy level (e.g. 'C-Level', 'Director', 'Team Lead').
        level: Numerical ranking (e.g. 1 for Executive, 2 for VP, etc.).
        parent_hierarchy_level_id: Optional parent hierarchy level ID.
        manager_function_id: Optional default manager function ID for this tier.
    """

    name: str
    level: int
    hierarchy_level_id: Optional[int] = None
    parent_hierarchy_level_id: Optional[int] = None
    manager_function_id: Optional[int] = None


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
        function_id: Unique primary key identifier.
        name: Title of the function (e.g. 'Chief Technology Officer', 'Project Manager').
        hierarchy_level_id: Associated hierarchy level ID.
        function_type_id: Optional associated function type ID.
        manager_function_id: Direct reporting manager function ID.
        dual_manager_function_id: Optional secondary / dotted-line manager function ID.
    """

    name: str
    hierarchy_level_id: int
    function_id: Optional[int] = None
    function_type_id: Optional[int] = None
    manager_function_id: Optional[int] = None
    dual_manager_function_id: Optional[int] = None


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
