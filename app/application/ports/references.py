"""Minimal catalog projections needed by authorized project workflows."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FunctionReference:
    """Hierarchy labels used to identify a project's managing function."""

    function_id: int | None
    name: str
    hierarchy_level: int
    manager_function_id: int | None


@dataclass(frozen=True)
class EmployeeReference:
    """Occupant names without contact details, staffing, or employee codes."""

    function_id: int | None
    firstname: str
    lastname: str


@dataclass(frozen=True)
class PoolReference:
    """Pool selection label and defined capacity, without configuration notes."""

    id: int | None
    name: str
    capacity_fte: float | None


@dataclass(frozen=True)
class PoolGroupReference:
    """Container pool identity using the existing Gantt group transport name."""

    id: int | None
    name: str


@dataclass(frozen=True)
class PoolHierarchyMember:
    """Transient Gantt edge; both group fields identify container pools."""

    group_id: int
    pool_id: int | None = None
    child_group_id: int | None = None


@dataclass(frozen=True)
class TypeReference:
    """Project-template selector identity without administration notes."""

    id: int
    name: str
    is_general: bool


@dataclass(frozen=True)
class PropertyReference:
    """Property labels needed to format current project filters and columns."""

    param_id: str
    param_name: str
    param_type: str
    alias: str | None


@dataclass(frozen=True)
class TagReference:
    """Tag selection identity without usage counts or shared assignments."""

    id: int | None
    tag: str
    tag_group_id: int | None
    tag_group_name: str | None
