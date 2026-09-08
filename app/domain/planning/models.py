"""Step / Milestone domain model for project schedule management."""

from dataclasses import dataclass
from enum import Enum


@dataclass
class Milestone:
    """Represents a project step or milestone deliverable.

    Attributes:
        project_id: Reference to parent project ID (integer primary key).
        task_name: Description of the task, step, or milestone deliverable.
        start_date: Start date string in ISO format (YYYY-MM-DD).
        end_date: End date string in ISO format (YYYY-MM-DD).
        phase: Project phase or category (e.g. 'Phase 1 - Inception').
        progress_pct: Completion percentage from 0 to 100.
        predecessor_id: Optional ID of predecessor step.
        id: Optional unique numeric step ID.
    """

    project_id: int
    task_name: str
    start_date: str
    end_date: str
    phase: str = "General"
    progress_pct: int = 0
    predecessor_id: int | None = None
    id: int | None = None


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
    id: int | None = None
    predecessor_task_id: int | None = None
    predecessor_project_id: str | None = None
    link_type: str = "FS"
    lag_days: int = 0
    predecessor_name: str | None = None
    predecessor_project_name: str | None = None


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
    dependency_id: int | None = None
