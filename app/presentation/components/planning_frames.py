"""Task DataFrame formatting for planning displays and historical adapters."""

import pandas as pd

from app.application.ports.planning import TaskRow


def tasks_frame(rows: list[TaskRow], *, project_labels: bool = False) -> pd.DataFrame:
    """Keep the planner's established columns even when a project has no tasks."""
    return pd.DataFrame(
        rows,
        columns=[
            "id",
            "project_id",
            "task_name",
            "phase",
            "start_date",
            "end_date",
            "progress_pct",
            "description",
            "predecessor_id",
            "project_name" if project_labels else "predecessor_name",
        ],
    )
