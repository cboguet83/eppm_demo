"""Real planning component mutations, safe failures, and injected data isolation."""

from contextlib import closing
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.infrastructure.database.connection import get_db
from app.main import create_planning_service, create_planning_workspace
from app.presentation.components.planning_data import load_planning_catalog
from app.presentation.components.planning_events import validate_event
from app.infrastructure.database.schema_init import init_db


def planning_app(path: str) -> None:
    """Run the real planner with optional pre-rerun component callbacks."""
    import streamlit as st
    from app.main import create_planning_workspace
    from app.presentation.pages.planning import (
        render_planning_milestones,
        _handle_gantt_component_change,
    )

    workspace = create_planning_workspace(path)
    event = st.session_state.pop("before_event", None)
    if event:
        st.session_state["planning_lazy_gantt"] = event
        _handle_gantt_component_change("planning_lazy_gantt", workspace)
    render_planning_milestones(workspace)


@pytest.fixture
def database(tmp_path: Path) -> str:
    path = str(tmp_path / "screen.db")
    init_db(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("INSERT INTO project(id,name) VALUES(1,'Project')")
    create_planning_service(path).create_milestone(
        1, "First", "General", "2026-01-01", "2026-01-02", 0
    )
    return path


def test_gantt_create_edit_progress_and_delete_use_real_application_transactions(
    database: str,
) -> None:
    app = AppTest.from_function(planning_app, args=(database,), default_timeout=30)
    app.session_state["ms_multi_projects"] = [1]
    service = create_planning_service(database)
    with patch(
        "app.presentation.pages.planning._interactive_gantt", return_value=None
    ) as component:
        app.run()
        assert not app.exception and not app.error
        component.return_value = {
            "action": "create_step_full",
            "project_id": "1",
            "task_name": "Created",
            "phase": "Build",
            "start_date": "2026-01-03",
            "end_date": "2026-01-05",
            "progress_pct": "10",
            "description": "Details",
            "dependencies": [{"predecessor_task_id": 1}],
            "nonce": "create",
        }
        app.run()
        assert not app.exception and not app.error
        rows = service.get_milestones_by_project(1)
        assert len(rows) == 2
        task_id = next(row["id"] for row in rows if row["task_name"] == "Created")
        assert service.get_task_dependencies(task_id)[0]["predecessor_task_id"] == 1
        component.return_value = {
            "action": "update_task_full",
            "id": str(task_id),
            "task_name": "Edited",
            "phase": "Build",
            "start_date": "2026-01-04",
            "end_date": "2026-01-06",
            "progress_pct": 25,
            "description": "Updated",
            "dependencies": [],
            "nonce": "edit",
        }
        app.run()
        assert not app.exception and not app.error
        assert service.get_milestone_by_id(task_id)["task_name"] == "Edited"
        assert service.get_task_dependencies(task_id) == []
        component.return_value = None
        app.session_state["before_event"] = {
            "action": "update_progress",
            "id": task_id,
            "progress": 500,
            "nonce": "progress",
        }
        app.run()
        assert not app.exception and not app.error
        assert service.get_milestone_by_id(task_id)["progress_pct"] == 100
        component.return_value = {"action": "delete_step", "id": task_id, "nonce": "delete"}
        app.run()
        assert not app.exception and not app.error
        assert service.get_milestone_by_id(task_id) is None
        assert len(service.get_milestones_by_project(1)) == 1


def test_adding_task_keeps_multi_project_scope_and_focuses_the_created_project(database: str) -> None:
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("INSERT INTO project(id,name) VALUES(2,'Second project')")
    app = AppTest.from_function(planning_app, args=(database,), default_timeout=30)
    app.session_state["ms_multi_projects"] = [1, 2]
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as component:
        app.run()
        token = app.session_state["planning_chart_snapshot"]["token"]
        app.session_state["before_event"] = {"action": "load_project_tasks", "project_ids": [1], "scope_token": token, "nonce": "load-one"}
        app.run()
        component.return_value = {
            "action": "create_step_full", "project_id": 2, "task_name": "Added here",
            "phase": "Build", "start_date": "2026-01-03", "end_date": "2026-01-05",
            "progress_pct": 0, "dependencies": [], "nonce": "create-two",
        }
        app.run()
        assert not app.exception and not app.error
        snapshot = app.session_state["planning_chart_snapshot"]
        assert snapshot["token"] == token and set(snapshot["loaded"]) == {1, 2}
        payloads = [call.kwargs["patch"] for call in component.call_args_list if "patch" in call.kwargs]
        created = next(payload for payload in payloads if payload.get("focus_project_id") == 2)
        assert created["scope_token"] == token
        assert created["replace_projects"] == [2]
        assert any(task["name"] == "Added here" for task in created["tasks"])


@pytest.mark.parametrize(
    "change,message",
    [
        ({"dependencies": 42}, "dependency"),
        ({"dependencies": [42]}, "dependency"),
        ({"progress_pct": None}, "number"),
        ({"task_name": ["bad"]}, "text"),
        ({"end_date": "2025-01-01"}, "after"),
        ({"dependencies": [{"predecessor_task_id": 999}]}, "constraint"),
    ],
)
def test_malformed_or_conflicting_gantt_create_does_not_leave_a_task(
    database: str,
    change: dict,
    message: str,
) -> None:
    app = AppTest.from_function(planning_app, args=(database,), default_timeout=30)
    event = {
        "action": "create_step_full",
        "project_id": 1,
        "task_name": "Invalid",
        "phase": "",
        "start_date": "2026-01-01",
        "end_date": "2026-01-02",
        "progress_pct": 0,
        "dependencies": [],
        "nonce": "invalid",
        **change,
    }
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=event):
        app.run()
    assert not app.exception
    assert any(message in error.value.lower() for error in app.error)
    assert len(create_planning_service(database).get_all_milestones()) == 1
    assert app.session_state["last_gantt_nonce"] == "invalid"
    assert not any("FOREIGN KEY" in error.value for error in app.error)


@pytest.mark.parametrize("action", ["update_task_full", "delete_step"])
def test_stale_gantt_mutations_report_missing_record_without_success(
    database: str, action: str
) -> None:
    app = AppTest.from_function(planning_app, args=(database,), default_timeout=30)
    event = {
        "action": action,
        "id": 999,
        "task_name": "Missing",
        "phase": "",
        "start_date": "2026-01-01",
        "end_date": "2026-01-02",
        "progress_pct": 0,
        "nonce": "stale",
    }
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=event):
        app.run()
    assert not app.exception
    assert any("no longer exists" in error.value for error in app.error)
    assert len(create_planning_service(database).get_all_milestones()) == 1


def test_bad_callback_is_consumed_once_and_cannot_change_progress(database: str) -> None:
    app = AppTest.from_function(planning_app, args=(database,), default_timeout=30)
    app.session_state["before_event"] = {
        "action": "update_progress",
        "id": 1,
        "progress": [],
        "nonce": "bad-progress",
    }
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None):
        app.run()
    assert not app.exception and app.error
    assert app.session_state["last_gantt_nonce"] == "bad-progress"
    assert create_planning_service(database).get_milestone_by_id(1)["progress_pct"] == 0
    with pytest.raises(ValueError, match="project_ids"):
        validate_event({"project_ids": 1})
    assert validate_event({"description": None, "id": "1"}) == {"description": "", "id": 1}


def test_task_bundle_reads_tags_and_assignments_from_the_same_snapshot(database: str) -> None:
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO task_tag(task_id,free_tag) VALUES(1,'Before')")
        connection.execute("INSERT INTO resource_pool(id,name,capacity_fte) VALUES(1,'Pool',1)")
        connection.execute(
            "INSERT INTO resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) VALUES(1,1,1,0.5)"
        )
    held = get_db(database)
    changed = []

    def commit_during_hydration(statement: str) -> None:
        if "FROM task_dependencies" not in statement or changed:
            return
        with closing(sqlite3.connect(database)) as writer, writer:
            writer.execute("UPDATE project_task SET task_name='After' WHERE id=1")
            writer.execute("UPDATE task_tag SET free_tag='After' WHERE task_id=1")
            writer.execute("UPDATE resource_pool_assignment SET fte_assigned=0.75 WHERE task_id=1")
        changed.append(True)

    held.set_trace_callback(commit_during_hydration)
    service = create_planning_service(database)
    with patch("app.infrastructure.repositories.planning.get_db", return_value=held):
        bundle = service.read_task_bundle([1])
    assert changed == [True]
    assert bundle.tasks[0]["task_name"] == "First"
    assert bundle.tags[1][0]["free_tag"] == "Before"
    assert bundle.pools[1][0]["fte"] == 0.5
    fresh = service.read_task_bundle([1])
    assert fresh.tasks[0]["task_name"] == fresh.tags[1][0]["free_tag"] == "After"
    assert fresh.pools[1][0]["fte"] == 0.75


def test_injected_display_caches_keep_databases_separate(database: str, tmp_path: Path) -> None:
    other = str(tmp_path / "other.db")
    init_db(other)
    with closing(sqlite3.connect(other)) as connection, connection:
        connection.execute("INSERT INTO project(id,name) VALUES(1,'Other database')")
    first, second = create_planning_workspace(database), create_planning_workspace(other)
    one = load_planning_catalog(first, first.revision())[0]
    two = load_planning_catalog(second, second.revision())[0]
    assert one.iloc[0]["name"] == "Project"
    assert two.iloc[0]["name"] == "Other database"


def test_non_list_dependencies_are_rejected_by_application_even_without_the_ui(
    database: str,
) -> None:
    service = create_planning_service(database)
    with pytest.raises(ValueError, match="dependency"):
        service.create_milestone(1, "Invalid", "", "2026-01-01", "2026-01-02", 0, dependencies=42)
    assert len(service.get_all_milestones()) == 1


def catalog_failure_app(error_name: str) -> None:
    """Exercise safe catalog failures at the actual presentation boundary."""
    from app.application import exceptions
    from app.presentation.pages.planning import planning_errors

    @planning_errors
    def render() -> None:
        raise getattr(exceptions, error_name)("Catalog temporarily unavailable.")

    render()


def project_tag_dialog_app(path: str) -> None:
    """Render the real Gantt project-tag editor."""
    from app.main import create_planning_workspace
    from app.presentation.pages.planning import _manage_project_tags_dialog

    _manage_project_tags_dialog(1, "Project", create_planning_workspace(path))


def test_project_tag_dialog_escapes_free_tag_labels(database: str) -> None:
    from app.domain.tags.models import ProjectTag
    from app.main import create_tag_service

    create_tag_service(database).create_project_tag(
        ProjectTag(project_id=1, free_tag="<b>literal & tag</b>")
    )
    app = AppTest.from_function(project_tag_dialog_app, args=(database,)).run()
    assert not app.exception and not app.error
    assert any("&lt;b&gt;literal &amp; tag&lt;/b&gt;" in item.value for item in app.markdown)


@pytest.mark.parametrize(
    "error_name",
    [
        "OrganizationStorageError",
        "ProjectStorageError",
        "ProjectTypeStorageError",
        "SchemaStorageError",
    ],
)
def test_planning_handles_failures_from_each_injected_catalog(error_name: str) -> None:
    app = AppTest.from_function(catalog_failure_app, args=(error_name,)).run()
    assert not app.exception
    assert [error.value for error in app.error] == ["Catalog temporarily unavailable."]
