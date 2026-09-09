"""Real transaction regressions for schedule replacement and project link drafts."""

from contextlib import closing
from pathlib import Path
import sqlite3
import io
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.application.exceptions import PlanningConflictError
from app.domain.planning.schedule_template import parse_template
from app.domain.resources.models import PoolAssignment, ResourcePool, ResourcePoolGroup
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.schema_init import init_db
from app.main import create_planning_service, create_project_service, create_resource_pool_service


HEADER = "step_number,task_name,start_date,end_date,progress_pct,dependencies\n"
VALID = HEADER + "1,New first,2026-01-01,2026-01-02,0,\n2,New second,2026-01-03,2026-01-04,50,step:1:FS:0\n"


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
    (VALID.replace("step:1", "step:9"), "Unknown predecessor"),
    (VALID.replace("step:1", "step:2"), "self-link"),
    (VALID.replace("step:1:FS:0", "task:999:FS:0"), "External task"),
    (VALID.replace("step:1:FS:0", "task:1:FS:0"), "use a step reference"),
    (VALID.replace("step:1:FS:0", "project:1:FS:0"), "refers to this project"),
    (VALID.replace("step:1:FS:0", "project:999:FS:0"), "missing"),
    (VALID.replace("step:1:FS:0", "step:1:XX:0"), "Dependency type"),
    (VALID.replace("step:1:FS:0", "step:1:FS:bad"), "lag"),
    (VALID.replace("step:1:FS:0", "bad"), "Dependencies must use"),
    (VALID.replace("step:1:FS:0", "step:1:FS:0;step:1:FS:0"), "Duplicate dependency"),
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
from app.main import create_project_workspace
from app.presentation.components.project_dialogs import open_edit_project_dialog
open_edit_project_dialog(1, create_project_workspace({database!r}), read_only=True)
''').run()
    assert not app.exception
    assert all(widget.disabled for widget in app.text_input)
    assert all(widget.disabled for widget in app.number_input)
    next(button for button in app.button if button.label == "Enable editing").click().run()
    assert not app.exception
    assert any(not widget.disabled for widget in app.text_input)
    assert any(not widget.disabled for widget in app.number_input)
    assert len(app.dataframe) == 1


def test_group_popup_includes_allocations_from_descendants(database: str) -> None:
    resources = create_resource_pool_service(database)
    group = resources.create_pool_group(ResourcePoolGroup(name="Group"), pool_ids=[1])
    with patch("app.presentation.components.action_table.action_table", return_value=None) as table:
        app = AppTest.from_string(f'''
from app.main import create_planning_workspace
from app.presentation.pages.planning import _pool_allocations_dialog
_pool_allocations_dialog(0, create_planning_workspace({database!r}), group_id={group})
''').run()
    assert not app.exception and not app.error
    assert len(table.call_args.args[0]) == 2
    assert table.call_args.args[2] == {"open":"Go to"}


def test_import_dialog_explains_invalid_upload_without_changing_data(database: str) -> None:
    before = snapshot(database)
    invalid = VALID.replace("step:1", "step:999").encode()
    with patch("streamlit.file_uploader", side_effect=lambda *args, **kwargs: io.BytesIO(invalid)):
        app = AppTest.from_string(f'''
from app.main import create_planning_workspace
from app.presentation.pages.planning import _schedule_csv_dialog
_schedule_csv_dialog(create_planning_workspace({database!r}), 1, "import_csv_template")
''').run()
    assert not app.exception
    assert "Unknown predecessor" in app.error[0].value
    assert "Nothing is deleted" in app.warning[0].value
    assert not any(button.label == "Replace project schedule" for button in app.button)
    assert snapshot(database) == before


def test_template_preserves_existing_multi_task_cycle_warning_behavior(database: str) -> None:
    content = VALID.replace("2026-01-02,0,", "2026-01-02,0,step:2:FS:0")
    service = create_planning_service(database)
    assert service.replace_project_template(1, content) == 2
    assert len(service.get_dependencies_for_project(1)) == 2
