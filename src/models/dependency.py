"""Task Dependency and Constraint Validation Models."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class LinkType(str, Enum):
    """Supported dependency link types."""

    FINISH_TO_START = "FS"
    FINISH_TO_FINISH = "FF"
    START_TO_START = "SS"
    START_TO_FINISH = "SF"

    @classmethod
    def get_display_name(cls, value: str) -> str:
        """Returns user-friendly display name for link type code."""
        mapping = {
            "FS": "Finish-to-Start (FS)",
            "FF": "Finish-to-Finish (FF)",
            "SS": "Start-to-Start (SS)",
            "SF": "Start-to-Finish (SF)",
        }
        return mapping.get(value, value)


@dataclass
class TaskDependency:
    """Represents a predecessor dependency for a project task/step.

    Attributes:
        id: Unique dependency record ID.
        task_id: ID of the successor task.
        predecessor_task_id: ID of the predecessor task (None if linking whole project).
        predecessor_project_id: Project code if external project dependency.
        link_type: Dependency type ('FS', 'FF', 'SS', 'SF').
        lag_days: Offset in days (e.g. +2 for lag, -1 for lead time).
        predecessor_name: Display label for the predecessor.
        predecessor_project_name: Display label for the predecessor project.
    """

    task_id: int
    id: Optional[int] = None
    predecessor_task_id: Optional[int] = None
    predecessor_project_id: Optional[str] = None
    link_type: str = "FS"
    lag_days: int = 0
    predecessor_name: Optional[str] = None
    predecessor_project_name: Optional[str] = None


@dataclass
class DependencyViolation:
    """Represents a detected scheduling constraint violation.

    Attributes:
        dependency_id: Dependency ID.
        task_id: Successor task ID.
        task_name: Successor task name.
        predecessor_label: Name of predecessor task or project.
        link_type: Link type ('FS', 'FF', 'SS', 'SF').
        lag_days: Day offset.
        required_date: Minimum/expected date required by constraint.
        actual_date: Actual date scheduled on task.
        message: Human-readable explanation.
    """

    task_id: int
    task_name: str
    predecessor_label: str
    link_type: str
    lag_days: int
    required_date: str
    actual_date: str
    message: str
    dependency_id: Optional[int] = None
