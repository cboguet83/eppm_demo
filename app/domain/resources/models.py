"""Domain models for recursive resource pools, mappings, and assignments."""

from dataclasses import dataclass, field
from typing import NotRequired, TypedDict


class CapacityAssignment(TypedDict):
    """Resolved assignment consumed by capacity calculations and table rendering."""

    id: int
    project_id: int
    project_name: str
    task_id: int | None
    task_name: str
    fte_assigned: float
    start_date: str
    end_date: str
    is_custom_period: bool
    notes: str
    schedule_anchor: NotRequired[str]
    offset_days: NotRequired[int]
    duration_days: NotRequired[int]


class AssignmentLink(TypedDict):
    """Compact allocation attached to a planning project or task."""

    id: int
    pool_id: int
    pool_name: str
    fte: float
    start_date: str | None
    end_date: str | None


class AssignmentRow(TypedDict):
    """Joined assignment read model; optional dates have not yet been resolved."""

    id: int
    pool_id: int
    pool_name: str
    project_id: int
    project_name: str
    task_id: int | None
    task_name: str | None
    task_start_date: str | None
    task_end_date: str | None
    fte_assigned: float
    custom_start_date: str | None
    custom_end_date: str | None
    effective_start_date: str | None
    effective_end_date: str | None
    notes: str | None
    schedule_anchor: NotRequired[str | None]
    offset_days: NotRequired[int | None]
    duration_days: NotRequired[int | None]


class ProjectPoolStatus(TypedDict):
    """Project demand compared with the pool's date-dependent capacity."""

    pool_id: int
    pool_name: str
    pool_capacity_fte: float
    minimum_capacity_fte: float
    project_peak_assigned_fte: float
    is_overassigned: bool
    excess_fte: float
    overallocated_dates: list[str]
    assignments_count: int


@dataclass
class ResourcePool:
    """Represents a capacity pool of resources (teams and/or functions).

    Attributes:
        name: Unique label for the resource pool.
        id: Unique primary key identifier.
        description: Informational notes / description of the pool.
        capacity_fte: Optional user-defined pool capacity limit. When omitted,
            the calculated assigned capacity supplies the limit.
        created_at: ISO timestamp of creation.
        hierarchy_type_id: Optional shared hierarchy classification.
        pool_type_id: Required pool classification; Human (1) is the default.
        parent_pool_id: Optional parent; pools with children are capacity containers.
    """

    name: str
    id: int | None = None
    description: str = ""
    capacity_fte: float | None = None
    created_at: str | None = None
    hierarchy_type_id: int | None = None
    pool_type_id: int = 1
    parent_pool_id: int | None = None


@dataclass(frozen=True)
class PoolCapacityException:
    """Inclusive absolute FTE reduction; overlapping reductions accumulate."""

    pool_id: int
    start_date: str
    end_date: str
    reduction_fte: float
    reason: str = ''
    id: int | None = None


@dataclass
class PoolMapping:
    """Represents the mapping of a team or function to a resource pool.

    Attributes:
        pool_id: ID of the parent resource pool.
        target_type: 'team', 'employee', or 'function'.
        target_id: ID of the mapped team, employee, or function.
        allocation_pct: Fractional percentage allocated to this pool (0.0 to 100.0).
        id: Unique primary key identifier.
    """

    pool_id: int
    target_type: str
    target_id: int
    allocation_pct: float = 100.0
    id: int | None = None


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
        schedule_anchor: Relative schedule origin, either start or end.
        offset_days: Calendar days forward from the origin; negative means before.
        duration_days: Positive inclusive allocation duration in calendar days.
    """

    pool_id: int
    project_id: int
    fte_assigned: float
    task_id: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    id: int | None = None
    notes: str = ""
    schedule_anchor: str | None = None
    offset_days: int | None = None
    duration_days: int | None = None


@dataclass
class PoolResourceContribution:
    """Details of a unique resource contributing to a pool's assigned capacity.

    Contributions describe employees or vacant functions mapped to a pool.

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
        resource_type: ``employee`` for occupied functions or ``function`` for
            vacant functions.
    """

    function_id: int
    function_name: str
    nominal_fte: float
    effective_allocation_pct: float
    effective_fte: float
    source_type: str
    source_name: str
    is_deduplicated: bool = False
    employee_id: int | None = None
    employee_name: str | None = None
    resource_type: str = "function"

    @property
    def resource_id(self) -> int:
        """Return the employee ID or the vacant function ID."""
        return self.employee_id if self.employee_id is not None else self.function_id

    @property
    def resource_name(self) -> str:
        """Return the employee name or the vacant function name."""
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
        total_capacity_fte: Theoretical pool capacity shown in the grid. This is
            the defined capacity when present, otherwise assigned capacity.
        defined_capacity_fte: User-defined theoretical pool capacity, if configured.
        assigned_capacity_fte: Capacity calculated from unique assigned resources.
        has_assigned_resources: Whether at least one valid resource contributes capacity.
        effective_capacity_fte: Base capacity used for demand checks. This coalesces
            assigned capacity with theoretical capacity when no resource is assigned.
        peak_assigned_fte: Maximum assigned FTE active on any single day.
        total_assigned_fte_scalar: Simple scalar sum of all active assignments.
        is_overassigned: True when demand exceeds effective capacity on any date.
        peak_excess_fte: Largest single-day excess over effective capacity.
        contributing_resources: List of employee and vacant-function contributions.
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
    contributing_resources: list[PoolResourceContribution] = field(default_factory=list)
    assignments: list[CapacityAssignment] = field(default_factory=list)
    daily_overassignments: list[DailyOverassignment] = field(default_factory=list)
    overassignment_intervals: list[str] = field(default_factory=list)
    daily_usage: dict[str, float] = field(default_factory=dict)
    defined_capacity_fte: float | None = None
    assigned_capacity_fte: float = 0.0
    daily_assigned_capacity: dict[str, float] = field(default_factory=dict)
    has_assigned_resources: bool = False
    effective_capacity_fte: float = 0.0
    daily_effective_capacity: dict[str, float] = field(default_factory=dict)

    @property
    def capacity_calendar(self) -> dict[str, float]:
        """Return effective date overrides, retaining existing staffing snapshots."""
        return self.daily_effective_capacity or (self.daily_assigned_capacity if self.has_assigned_resources else {})


@dataclass(frozen=True)
class PoolTag:
    """Dictionary tag associated with a resource pool."""

    id: int
    pool_id: int
    tag_id: int
    tag_name: str
    tag_group_name: str | None


@dataclass(frozen=True)
class PoolTagChoice:
    """Tag dictionary choice for a pool editor."""

    id: int
    tag: str
    tag_group_id: int | None
    tag_group_name: str | None


@dataclass(frozen=True)
class PoolCapacitySummary:
    """Lightweight capacity totals for pool lists and selectors."""

    pool_id: int
    pool_name: str
    total_capacity_fte: float
    assigned_capacity_fte: float
    peak_assigned_fte: float
    is_overassigned: bool
    peak_excess_fte: float
