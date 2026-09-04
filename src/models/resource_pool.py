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
        created_at: ISO timestamp of creation.
    """

    name: str
    id: Optional[int] = None
    description: str = ""
    created_at: Optional[str] = None


@dataclass
class PoolMapping:
    """Represents the mapping of a team or function to a resource pool.

    Attributes:
        pool_id: ID of the parent resource pool.
        target_type: 'team' or 'function'.
        target_id: ID of the mapped team or function.
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
    """Details of an individual function contributing to a resource pool's capacity.

    Attributes:
        function_id: Unique function ID.
        function_name: Title of the function.
        nominal_fte: Intrinsic FTE capacity of the function (e.g. 1.0).
        effective_allocation_pct: Final allocation percentage applied (0 to 100).
        effective_fte: Calculated capacity contribution (nominal_fte * pct / 100).
        source_type: 'direct' or 'team'.
        source_name: Name of the team if sourced via a team, or 'Direct Mapping'.
        is_deduplicated: True if function appeared in both team and direct mapping.
    """

    function_id: int
    function_name: str
    nominal_fte: float
    effective_allocation_pct: float
    effective_fte: float
    source_type: str
    source_name: str
    is_deduplicated: bool = False


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
        total_capacity_fte: Total pool capacity in FTE calculated from unique functions.
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
