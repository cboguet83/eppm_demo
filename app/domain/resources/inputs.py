"""Typed snapshots for pure resource-capacity calculations."""

from dataclasses import dataclass, field

from app.domain.organization.models import Employee, EmployeeCalendarException, OrgFunction, Team
from app.domain.resources.models import AssignmentRow, PoolMapping, ResourcePool


@dataclass
class CapacityInputs:
    """Consistent source records for one pool; shared catalogs are read-only."""

    pool_id: int
    pool: ResourcePool | None = None
    functions: list[OrgFunction] = field(default_factory=list)
    teams: list[Team] = field(default_factory=list)
    employees: list[Employee] = field(default_factory=list)
    exceptions: list[EmployeeCalendarException] = field(default_factory=list)
    mappings: list[PoolMapping] = field(default_factory=list)
    team_functions: dict[int, list[int]] = field(default_factory=dict)
    assignments: list[AssignmentRow] = field(default_factory=list)
    project_bounds: dict[int, tuple[str | None, str | None]] = field(default_factory=dict)
