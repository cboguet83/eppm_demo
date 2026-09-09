"""Numbered CSV exports preserve schedule values and handle quoted text."""

import csv
import io
from pathlib import Path

from app.domain.planning.csv_export import export_schedule
from app.domain.planning.csv_import import get_csv_template, parse_csv
from app.infrastructure.database.schema_init import init_db
from app.main import create_planning_service, create_project_service


def test_project_schedule_exports_actual_tasks_in_order_numbered_from_one(tmp_path: Path) -> None:
    path = str(tmp_path / "schedule.db")
    init_db(path)
    projects = create_project_service(path)
    project = projects.create_project(name="Schedule")
    other = projects.create_project(name="Other")
    service = create_planning_service(path)
    service.create_milestone(project, "Second", "Build", "2026-01-03", "2026-01-05", 50)
    service.create_milestone(other, "Excluded", "Build", "2026-01-01", "2026-01-02", 0)
    service.create_milestone(project, 'First, "quoted"', "Design", "2026-01-01", "2026-01-02", 100, description="Line one\nLine two")

    content = service.export_schedule(project)

    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    assert reader.fieldnames[0] == "step_number"
    assert [row["step_number"] for row in rows] == ["1", "2"]
    assert [row["task_name"] for row in rows] == ['First, "quoted"', "Second"]
    assert rows[0]["description"] == "Line one\nLine two"
    assert rows[1]["progress_pct"] == "50"
    assert len(parse_csv(content)) == 2


def test_empty_export_and_template_have_numbered_first_column() -> None:
    assert export_schedule([]).splitlines()[0].startswith("step_number,")
    assert len(export_schedule([]).splitlines()) == 1
    rows = list(csv.DictReader(io.StringIO(get_csv_template())))
    assert [row["step_number"] for row in rows] == ["1", "2", "3"]
    assert len(parse_csv(get_csv_template())) == 3
