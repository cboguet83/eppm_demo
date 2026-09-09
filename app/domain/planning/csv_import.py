"""CSV task parsing using only the standard library and scheduling rules."""

import csv
from decimal import Decimal, InvalidOperation
import io

from app.domain.planning.records import TaskValues
from app.domain.planning.rules import normalize_task


def get_csv_template() -> str:
    """Return the existing import columns and example milestones."""
    return (
        "step_number,task_name,phase,start_date,end_date,progress_pct,description,predecessor_id\n"
        "1,Architecture Scoping,Phase 1 - Inception,2026-06-01,2026-06-15,100,Define system blueprint,\n"
        "2,Architecture Milestone,Phase 1 - Inception,2026-06-15,2026-06-15,100,Sign-off on specs,1\n"
        "3,Core Build,Phase 2 - Build,2026-06-16,2026-07-30,50,Core API services,2\n"
    )


def parse_csv(content: str) -> list[TaskValues]:
    """Parse task rows and report safe, numbered validation errors.

    Optional progress retains the importer's default/clamp behavior. Optional
    predecessor IDs retain decimal-text support. Dates use the advertised ISO
    format; blank required values are errors instead of the string 'nan'.
    """
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), strict=True)
    try:
        fields = reader.fieldnames
        if not fields:
            raise ValueError("Uploaded CSV is empty.")
        missing = {"task_name", "start_date", "end_date"} - set(fields)
        if missing:
            raise ValueError("Missing required columns in CSV: " + ", ".join(sorted(missing)))
        records = []
        for number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"Row {number}: Too many CSV columns.")
            try:
                progress = int(Decimal(row.get("progress_pct") or "0"))
            except (InvalidOperation, ValueError, OverflowError):
                progress = 0
            try:
                predecessor = int(Decimal(row.get("predecessor_id") or ""))
            except (InvalidOperation, ValueError, OverflowError):
                predecessor = None
            values = TaskValues(
                task_name=row.get("task_name") or "",
                start_date=row.get("start_date") or "",
                end_date=row.get("end_date") or "",
                phase=row.get("phase") or "General",
                description=row.get("description") or "",
                progress_pct=progress,
                predecessor_id=predecessor,
            )
            try:
                records.append(normalize_task(values))
            except ValueError as exc:
                raise ValueError(f"Row {number}: {exc}") from exc
    except csv.Error as exc:
        raise ValueError("Failed to read CSV file: invalid CSV structure.") from exc
    if not records:
        raise ValueError("Uploaded CSV is empty.")
    return records
