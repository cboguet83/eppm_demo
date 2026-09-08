"""Project domain models and portfolio metrics data structures."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Project:
    """Represents an enterprise project record.

    Attributes:
        id: Unique project identifier (integer primary key).
        name: Project title or name.
        status: Project lifecycle status ('Draft', 'In Progress', etc.).
        planned_budget: Approved planned expenditure in USD.
        actual_budget: Cumulative actual spend in USD.
        dynamic_attributes: Key-value dictionary of dynamic schema values.
        function_id: Optional foreign key ID towards an organizational function (Project Manager).
        project_type_id: Type whose effective template governs this project's properties.
    """

    id: Optional[int] = None
    name: str = ""
    status: str = "Draft"
    planned_budget: float = 0.0
    actual_budget: float = 0.0
    dynamic_attributes: dict[str, Any] = field(default_factory=dict)
    function_id: Optional[int] = None
    project_type_id: int = 1


@dataclass(frozen=True)
class PortfolioMetrics:
    """Aggregated portfolio financial KPIs.

    Attributes:
        total_projects: Total number of active projects in portfolio.
        total_planned: Sum of planned budgets across all projects.
        total_actual: Sum of actual spend across all projects.
        variance: Net variance (total_planned - total_actual).
        burn_rate: Ratio of actual spend to planned budget (percentage).
    """

    total_projects: int = 0
    total_planned: float = 0.0
    total_actual: float = 0.0
    variance: float = 0.0
    burn_rate: float = 0.0
