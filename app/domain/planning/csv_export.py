"""Numbered schedule exports with standard CSV escaping."""

from collections.abc import Sequence
import csv
import io

from app.domain.planning.records import TaskValues


def export_schedule(tasks: Sequence[TaskValues]) -> str:
    """Export schedule values in their supplied order, numbered consecutively from 1."""
    output = io.StringIO(newline="")
    fields = ["task_name", "phase", "start_date", "end_date", "progress_pct", "description"]
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["step_number", *fields])
    for number, task in enumerate(tasks, start=1):
        writer.writerow([number, *(task.get(field, "") for field in fields)])
    return output.getvalue()
