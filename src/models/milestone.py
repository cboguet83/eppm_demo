"""Step / Milestone domain model for project schedule management."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Milestone:
    """Represents a project step or milestone deliverable.

    Attributes:
        project_id: Reference to parent project ID code.
        task_name: Description of the task, step, or milestone deliverable.
        start_date: Start date string in ISO format (YYYY-MM-DD).
        end_date: End date string in ISO format (YYYY-MM-DD).
        phase: Project phase or category (e.g. 'Phase 1 - Inception').
        progress_pct: Completion percentage from 0 to 100.
        predecessor_id: Optional ID of predecessor step.
        id: Optional unique numeric step ID.
    """

    project_id: str
    task_name: str
    start_date: str
    end_date: str
    phase: str = "General"
    progress_pct: int = 0
    predecessor_id: Optional[int] = None
    id: Optional[int] = None
