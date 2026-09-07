"""Domain data models for resource pools, pool mappings, and pool assignments."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TeamFunction:
    """Association linking a function to a team.

    Attributes:
        team_id: Associated team ID.
        function_id: Associated job function ID.
        id: Unique primary key identifier.
    """

    team_id: int
    function_id: int
    id: Optional[int] = None


@dataclass
class ResourcePool:
    """Represents a capacity pool of resources (teams and/or functions).

    Attributes:
        name: Unique label for the resource pool.
        id: Unique primary key identifier.
        description: Informational notes / description of the pool.
        capacity_fte: Optional user-defined pool capacity limit. When omitted,
            the calculated assigned capacity is used for backwards compatibility.
        created_at: ISO timestamp of creation.
    """

    name: str
    id: Optional[int] = None
    description: str = ""
    capacity_fte: Optional[float] = None
    created_at: Optional[str] = None


@dataclass
class PoolMapping:
    """Represents the mapping of a team or function to a resource pool.

    Attributes:
        pool_id: ID of the parent resource pool.
        target_type: 'team', 'employee', or legacy 'function'.
        target_id: ID of the mapped team, employee, or function.
        allocation_pct: Fractional percentage allocated to this pool (0.0 to 100.0).
        id: Unique primary key identifier.
    """

    pool_id: int
    target_type: str
    target_id: int
    allocation_pct: float = 100.0
    id: Optional[int] = None


@dataclass
class PoolAssignment:
    """Represents an allocation of FTE from a resource pool to a project or task.

    Attributes:
        pool_id: Associated resource pool ID.
        project_id: Target project ID.
        fte_assigned: Allocated Full-Time Equivalent capacity (must be >= 0).
        task_id: Optional project task / step ID. If None, assignment is at project level.
        start_date: Optional start date (YYYY-MM-DD). If None, spans full task/project period.
        end_date: Optional end date (YYYY-MM-DD). If None, spans full task/project period.
        id: Unique primary key identifier.
        notes: Contextual notes or role description.
    """

    pool_id: int
    project_id: int
    fte_assigned: float
    task_id: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    id: Optional[int] = None
    notes: str = ""


@dataclass
class PoolFunctionContribution:
    """Details of a unique resource contributing to a pool's assigned capacity.

    The historical class name is retained for API compatibility. New records are
    normally employee-based; legacy function-only pools continue to be supported.

    Attributes:
        function_id: Unique function ID.
        function_name: Title of the function.
        nominal_fte: Intrinsic FTE capacity of the function (e.g. 1.0).
        effective_allocation_pct: Final allocation percentage applied (0 to 100).
        effective_fte: Calculated capacity contribution (nominal_fte * pct / 100).
        source_type: 'direct' or 'team'.
        source_name: Name of the team if sourced via a team, or 'Direct Mapping'.
        is_deduplicated: True if function appeared in both team and direct mapping.
        employee_id: Employee ID when the contribution represents an employee.
        employee_name: Display name when the contribution represents an employee.
        resource_type: ``employee`` for normal records or ``function`` for legacy
            function-only records.
    """

    function_id: int
    function_name: str
    nominal_fte: float
    effective_allocation_pct: float
    effective_fte: float
    source_type: str
    source_name: str
    is_deduplicated: bool = False
    employee_id: Optional[int] = None
    employee_name: Optional[str] = None
    resource_type: str = "function"

    @property
    def resource_id(self) -> int:
        """Return the employee ID, falling back to the legacy function ID."""
        return self.employee_id if self.employee_id is not None else self.function_id

    @property
    def resource_name(self) -> str:
        """Return the employee name, falling back to the legacy function name."""
        return self.employee_name or self.function_name


@dataclass
class DailyOverassignment:
    """Record of an overassignment occurrence on a specific calendar date.

    Attributes:
        date: ISO date string (YYYY-MM-DD).
        capacity_fte: Total pool capacity available on that date.
        assigned_fte: Total FTE assigned active on that date.
        excess_fte: Assigned FTE minus capacity FTE (> 0).
    """

    date: str
    capacity_fte: float
    assigned_fte: float
    excess_fte: float


@dataclass
class PoolCapacityDetail:
    """Aggregated capacity, mapping breakdown, daily overassignments, and status of a pool.

    Attributes:
        pool_id: Pool ID.
        pool_name: Pool name.
        total_capacity_fte: Effective capacity limit used for demand checks. This is
            the defined capacity when present, otherwise assigned capacity.
        defined_capacity_fte: User-defined pool capacity, if configured.
        assigned_capacity_fte: Capacity calculated from unique assigned resources.
        peak_assigned_fte: Maximum assigned FTE active on any single day.
        total_assigned_fte_scalar: Simple scalar sum of all active assignments.
        is_overassigned: True if peak_assigned_fte > total_capacity_fte.
        peak_excess_fte: peak_assigned_fte - total_capacity_fte if overassigned, else 0.0.
        contributing_functions: List of individual function contributions.
        assignments: List of active assignments with resolved project and task names.
        daily_overassignments: List of dates where assignment exceeds pool capacity.
        overassignment_intervals: Human-readable summary of overassigned date ranges.
    """

    pool_id: int
    pool_name: str
    total_capacity_fte: float
    peak_assigned_fte: float
    total_assigned_fte_scalar: float
    is_overassigned: bool
    peak_excess_fte: float
    contributing_functions: List[PoolFunctionContribution] = field(default_factory=list)
    assignments: List[Dict[str, Any]] = field(default_factory=list)
    daily_overassignments: List[DailyOverassignment] = field(default_factory=list)
    overassignment_intervals: List[str] = field(default_factory=list)
    daily_usage: Dict[str, float] = field(default_factory=dict)
    defined_capacity_fte: Optional[float] = None
    assigned_capacity_fte: float = 0.0
    daily_assigned_capacity: Dict[str, float] = field(default_factory=dict)

    @property
    def contributing_resources(self) -> List[PoolFunctionContribution]:
        """Alias exposing the contribution list using current resource terminology."""
        return self.contributing_functions

    @property
    def peak_daily_fte(self) -> float:
        """Alias for peak_assigned_fte.

        Returns:
            float: Peak assigned FTE.
        """
        return self.peak_assigned_fte

    @property
    def total_capacity(self) -> float:
        """Alias for total_capacity_fte.

        Returns:
            float: Total capacity in FTE.
        """
        return self.total_capacity_fte
