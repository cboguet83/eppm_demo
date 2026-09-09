"""Real transaction regressions for schedule replacement and project link drafts."""

from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3
import io
import csv
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.application.exceptions import PlanningConflictError
from app.domain.planning.schedule_template import parse_template
from app.domain.resources.models import PoolAssignment, ResourcePool, ResourcePoolGroup
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.schema_init import init_db
from app.operator_services import create_planning_service, create_project_service, create_resource_pool_service


HEADER = "step_number,task_name,start_date,end_date,progress_pct,preceding_step,dependency_type,dependency_lag\n"
VALID = HEADER + "1,New first,2026-01-01,2026-01-02,0,,,\n2,New second,2026-01-03,2026-01-04,50,1,FS,0\n"


@pytest.fixture
def database(tmp_path: Path) -> str:
    path = str(tmp_path / "templates.db")
    init_db(path)
    projects = create_project_service(path)
    for name in ("Selected", "Predecessor", "Successor", "Unrelated"):
        projects.create_project(name=name)
    planning = create_planning_service(path)
    for project in range(1, 5):
        planning.create_milestone(project, f"Task {project}", "Build", "2026-01-01", "2026-01-04", 0)
    planning.add_dependency(1, predecessor_task_id=2)
    planning.add_dependency(3, predecessor_task_id=1)
    resources = create_resource_pool_service(path)
    pool = resources.create_pool(ResourcePool("Pool", capacity_fte=2))
    resources.create_assignment(PoolAssignment(pool, 1, .5))
    resources.create_assignment(PoolAssignment(pool, 1, .5, task_id=1))
    return path


def snapshot(path: str) -> dict[str, list[tuple]]:
    with closing(sqlite3.connect(path)) as connection:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                for table in ("project_task", "task_dependencies", "resource_pool_assignment", "project_link")}


@pytest.mark.parametrize("content,problem", [
    ("", "Missing required"), (HEADER, "no tasks"),
    (VALID.replace("New second", ""), "Row 3"),
    (VALID.replace("2026-01-03", "2026-02-03"), "Row 3"),
    (VALID.replace(",50,", ",150,"), "Progress"),
    (VALID.replace("2,New", "1,New"), "unique"),
    (VALID.replace("1,FS,0", "9,FS,0"), "Unknown predecessor"),
    (VALID.replace("1,FS,0", "2,FS,0"), "self-link"),
    (VALID.replace("1,FS,0", "task:999,FS,0"), "External task"),
    (VALID.replace("1,FS,0", "task:1,FS,0"), "use a step reference"),
    (VALID.replace("1,FS,0", "project:1,FS,0"), "refers to this project"),
    (VALID.replace("1,FS,0", "project:999,FS,0"), "missing"),
    (VALID.replace("1,FS,0", "1,XX,0"), "Dependency type"),
    (VALID.replace("1,FS,0", "1,FS,bad"), "lag"),
    (VALID.replace("1,FS,0", "bad,FS,0"), "positive integer"),
    (VALID.replace("1,FS,0", "1;1,FS;FS,0;0"), "Duplicate dependency"),
])
def test_invalid_replacement_preserves_tasks_links_and_allocations(database: str, content: str, problem: str) -> None:
    before = snapshot(database)
    with pytest.raises(ValueError, match=problem):
        create_planning_service(database).replace_project_template(1, content)
    assert snapshot(database) == before


def test_replacement_clears_old_schedule_and_allocations_but_preserves_project_links(database: str) -> None:
    projects = create_project_service(database)
    project = projects.get_project_by_id(1)
    projects.update_project(1, project.name, project.status, 0, 0, {}, custom_links=[{"url":"https://example.test", "alias":"Useful"}])
    service = create_planning_service(database)
    assert service.replace_project_template(1, VALID) == 2
    tasks = service.get_milestones_by_project(1)
    assert [task["task_name"] for task in tasks] == ["New first", "New second"]
    assert service.get_task_dependencies(tasks[1]["id"])[0]["predecessor_task_id"] == tasks[0]["id"]
    assert service.get_task_dependencies(3) == []
    assert len(service.get_milestones_by_project(2)) == 1
    assert create_resource_pool_service(database).get_assignments(project_id=1) == []
    assert projects.get_links(1) == [{"url":"https://example.test", "alias":"Useful"}]
    with closing(get_db(database)) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_storage_failure_rolls_back_deletion_and_partial_replacement(database: str) -> None:
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TRIGGER reject_replacement BEFORE INSERT ON project_task WHEN NEW.task_name='New second' BEGIN SELECT RAISE(ABORT,'rejected'); END")
    before = snapshot(database)
    with pytest.raises(PlanningConflictError):
        create_planning_service(database).replace_project_template(1, VALID)
    assert snapshot(database) == before


def test_export_round_trips_multiline_text_multiple_link_types_and_lags(database: str) -> None:
    service = create_planning_service(database)
    task = service.create_milestone(1, 'Quoted, "task"', "Design", "2026-02-01", "2026-02-03", 42,
        description="First line\nSecond line", dependencies=[
            {"predecessor_task_id":1, "link_type":"SS", "lag_days":-2},
            {"predecessor_project_id":4, "link_type":"FF", "lag_days":3},
        ])
    content = service.export_project_template(1)
    steps = parse_template(content)
    assert steps[1].values["description"] == "First line\nSecond line"
    assert {dep.kind for step in steps for dep in step.dependencies} == {"step", "task", "project"}
    service.replace_project_template(1, content)
    assert service.export_project_template(1) == content
    assert service.get_milestone_by_id(task) is None


@pytest.mark.parametrize("date_format,pattern", [("DD/MM/YYYY", "%d/%m/%Y"), ("MM/DD/YYYY", "%m/%d/%Y")])
def test_spreadsheet_reformatted_export_preserves_dates_on_reimport(database: str, date_format: str, pattern: str) -> None:
    service = create_planning_service(database)
    exported = service.export_project_template(1)
    rows = list(csv.DictReader(io.StringIO(exported)))
    # Simulate a spreadsheet changing the start-date cell while retaining ISO end dates.
    rows[0]["start_date"] = date.fromisoformat(rows[0]["start_date"]).strftime(pattern)
    rows[0]["task_name"] = "Edited in spreadsheet"
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    edited = output.getvalue()
    before = snapshot(database)
    with pytest.raises(ValueError, match="Row 2: Invalid start_date"):
        service.replace_project_template(1, edited)
    assert snapshot(database) == before
    preview = service.validate_project_template(1, edited, date_format=date_format)
    assert preview[0].values["start_date"] == "2026-01-01"
    service.replace_project_template(1, edited, date_format=date_format)
    assert service.export_project_template(1) == exported.replace("Task 1", "Edited in spreadsheet")


def test_ambiguous_dates_follow_selected_format_and_invalid_dates_preserve_schedule(database: str) -> None:
    content = VALID.replace("2026-01-01", "02/01/2026").replace("2026-01-02", "03/02/2026")
    # Use one task so later task chronology does not obscure the date-order check.
    content = "\n".join(content.splitlines()[:2]) + "\n"
    assert parse_template(content, date_format="DD/MM/YYYY")[0].values["start_date"] == "2026-01-02"
    assert parse_template(content, date_format="MM/DD/YYYY")[0].values["start_date"] == "2026-02-01"
    service = create_planning_service(database)
    before = snapshot(database)
    for bad in ("31/02/2026", "", "01/02/26"):
        with pytest.raises(ValueError, match="Row 2: Invalid start_date"):
            service.replace_project_template(1, content.replace("02/01/2026", bad), date_format="DD/MM/YYYY")
        assert snapshot(database) == before
    with pytest.raises(ValueError, match="Unsupported CSV date format"):
        parse_template(content, date_format="guess")


def test_import_defaults_to_day_first_and_previews_normalized_dates(database: str) -> None:
    content = VALID.replace("2026-01-01", "01/01/2026").encode()
    with patch("app.presentation.components.csv_upload.project_csv_upload", return_value=content.decode()):
        app = AppTest.from_string(f'''
from app.operator_services import create_planning_workspace
from app.presentation.pages.planning import _schedule_csv_dialog
_schedule_csv_dialog(create_planning_workspace({database!r}), 1, "import_csv_template")
''').run()
        assert app.selectbox(key="template_date_format_1").value == "DD/MM/YYYY"
        assert not app.exception
        assert not app.error
        assert app.dataframe[0].value.iloc[0]["start_date"] == "2026-01-01"
        app.selectbox(key="template_date_format_1").select("YYYY-MM-DD").run()
        assert "Invalid start_date" in app.error[0].value


def test_project_filter_uses_transitive_dependencies_and_terminates_on_cycles(database: str) -> None:
    service = create_planning_service(database)
    assert service.related_project_ids(1, "this") == [1]
    assert service.related_project_ids(1, "predecessors") == [1, 2]
    assert service.related_project_ids(1, "all") == [1, 2, 3]
    service.add_dependency(2, predecessor_task_id=3)
    assert service.related_project_ids(1, "predecessors") == [1, 2, 3]
    with pytest.raises(ValueError, match="Unknown"):
        service.related_project_ids(1, "invalid")


def test_project_creation_and_update_save_custom_links_atomically(database: str) -> None:
    service = create_project_service(database)
    project = service.create_project(name="With links", custom_links=[{"url":"https://example.test", "alias":"Docs"}])
    assert service.get_links(project)[0]["alias"] == "Docs"
    with pytest.raises(ValueError):
        service.update_project(project, "Must not change", "Draft", 0, 0, {}, custom_links=[{"url":"bad", "alias":"Bad"}])
    assert service.get_project_by_id(project).name == "With links"
    assert service.get_links(project)[0]["alias"] == "Docs"
    service.update_project(project, "Edited", "Draft", 0, 0, {}, custom_links=[{"url":"https://example.test/new", "alias":"New"}])
    assert service.get_links(project)[0]["alias"] == "New"
    with pytest.raises(ValueError):
        service.create_project(name="Must not exist", custom_links=[{"url":"bad", "alias":"Bad"}])
    assert len(service.get_planning_catalog()) == 5


def test_project_view_starts_read_only_and_explicit_button_enables_editing(database: str) -> None:
    app = AppTest.from_string(f'''
from app.operator_services import create_project_workspace
from app.presentation.components.project_dialogs import open_edit_project_dialog
open_edit_project_dialog(1, create_project_workspace({database!r}), read_only=True)
''').run()
    assert not app.exception
    assert all(widget.disabled for widget in app.text_input)
    assert all(widget.disabled for widget in app.number_input)
    next(button for button in app.button if button.label == "Edit project").click().run()
    assert not app.exception
    assert any(not widget.disabled for widget in app.text_input)
    assert any(not widget.disabled for widget in app.number_input)
    assert len(app.dataframe) == 1


def test_group_popup_includes_allocations_from_descendants(database: str) -> None:
    resources = create_resource_pool_service(database)
    group = resources.create_pool_group(ResourcePoolGroup(name="Group"), pool_ids=[1])
    with patch("app.presentation.components.action_table.action_table", return_value=None) as table:
        app = AppTest.from_string(f'''
from app.operator_services import create_planning_workspace
from app.presentation.pages.planning import _pool_allocations_dialog
_pool_allocations_dialog(0, create_planning_workspace({database!r}), group_id={group})
''').run()
    assert not app.exception and not app.error
    assert len(table.call_args.args[0]) == 2
    assert table.call_args.args[2] == {"open":"Go to"}


def test_import_dialog_explains_invalid_upload_without_changing_data(database: str) -> None:
    before = snapshot(database)
    invalid = VALID.replace("1,FS,0", "999,FS,0").encode()
    with patch("app.presentation.components.csv_upload.project_csv_upload", return_value=invalid.decode()):
        app = AppTest.from_string(f'''
from app.operator_services import create_planning_workspace
from app.presentation.pages.planning import _schedule_csv_dialog
_schedule_csv_dialog(create_planning_workspace({database!r}), 1, "import_csv_template")
''').run()
    assert not app.exception
    assert "Unknown predecessor" in app.error[0].value
    assert "Nothing is deleted" in app.warning[0].value
    assert not any(button.label == "Replace project schedule" for button in app.button)
    assert snapshot(database) == before


def test_template_preserves_existing_multi_task_cycle_warning_behavior(database: str) -> None:
    content = VALID.replace("2026-01-02,0,,,", "2026-01-02,0,2,FS,0")
    service = create_planning_service(database)
    assert service.replace_project_template(1, content) == 2
    assert len(service.get_dependencies_for_project(1)) == 2


def test_split_dependency_columns_round_trip_and_reject_mismatched_lists(database: str) -> None:
    service = create_planning_service(database)
    content = VALID.replace("1,FS,0", "1;task:2,FS;SS,0;-2")
    service.replace_project_template(1, content)
    exported = service.export_project_template(1)
    rows = list(csv.DictReader(io.StringIO(exported)))
    assert rows[1]["preceding_step"] == "1;task:2"
    assert rows[1]["dependency_type"] == "FS;SS"
    assert rows[1]["dependency_lag"] == "0;-2"
    assert "dependencies" not in rows[1]
    before = snapshot(database)
    for invalid in (content.replace("FS;SS", "FS"), content.replace("0;-2", "0;")):
        with pytest.raises(ValueError, match="same number"):
            service.replace_project_template(1, invalid)
        assert snapshot(database) == before


def test_clear_all_filters_resets_selection_and_resource_filter_state(database: str) -> None:
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as chart:
        app = AppTest.from_string(f'''
import streamlit as st
from app.operator_services import create_planning_workspace
from app.presentation.pages.planning import render_planning_milestones
if "initialized" not in st.session_state:
    st.session_state.initialized = True
    st.session_state.ms_multi_projects = [1]
    st.session_state.ms_planning_tag_filter = ["Stale tag"]
render_planning_milestones(create_planning_workspace({database!r}))
''', default_timeout=15).run()
        assert not app.exception
        assert not any(widget.key == "ms_planning_tag_filter" for widget in app.multiselect)
        next(button for button in app.button if button.label == "Clear all filters").click().run()
        assert not app.exception
        assert app.session_state["ms_multi_projects"] == []
        assert app.session_state["ms_planning_tag_filter"] == []
        assert chart.call_args.kwargs["filter_reset"] == 1
    assert create_planning_service(database).related_project_ids([1, 4], "all") == [1, 2, 3, 4]
