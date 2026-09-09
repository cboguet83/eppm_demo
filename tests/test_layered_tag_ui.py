"""Tag catalog dialogs, assignment editors, and component-event routing."""

from contextlib import closing
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.domain.tags.models import ProjectTag, TagDictionary, TagGroup, TaskTag
from app.operator_services import create_tag_service
from app.infrastructure.database.schema_init import init_db


@pytest.fixture
def database(tmp_path: Path) -> str:
    path = str(tmp_path / "tag-ui.db")
    init_db(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("INSERT INTO project(id,name) VALUES(1,'Delivery')")
        connection.executemany(
            "INSERT INTO project_task(id,project_id,task_name,start_date,end_date) VALUES(?,1,?,'2026-09-01','2026-09-03')",
            [(i, f"Task {i}") for i in range(1, 61)],
        )
    return path


def dialog(path: str, invocation: str) -> AppTest:
    """Keep the real dialog open across AppTest's full-script reruns."""
    app = AppTest.from_string(
        f"""
from dataclasses import asdict
import pandas as pd
from app.operator_services import create_tag_service
from app.presentation.components import tag_dialogs as dialogs
from app.presentation.components.tag_frames import get_all_tag_groups_frame, get_all_tags_frame
from app.presentation.i18n import set_current_locale
set_current_locale('en')
service=create_tag_service({path!r})
groups=get_all_tag_groups_frame(service.get_all_tag_groups())
tags=get_all_tags_frame(service.get_all_tags())
projects=pd.DataFrame([asdict(row) for row in service.project_choices()])
dialogs.{invocation}
""",
        default_timeout=15,
    ).run()
    assert not app.exception, [item.message for item in app.exception]
    return app


def test_used_dictionary_tag_deletion_explains_and_removes_its_assignments(database: str) -> None:
    service = create_tag_service(database)
    tag = service.create_tag(TagDictionary(tag="Assigned category"))
    service.create_project_tag(ProjectTag(project_id=1, tag_id=tag))
    service.create_task_tag(TaskTag(task_id=1, tag_id=tag))
    app = dialog(database, f"_open_delete_tag_dialog(service,{tag},'Assigned category')")
    assert "2 project, task, or resource-pool assignment(s)" in app.warning[0].value
    app.button[0].click().run()
    assert not app.exception and not app.error
    assert service.get_tag_by_id(tag) is None
    assert service.get_all_project_tags() == [] and service.get_all_task_tags() == []
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM project_task").fetchone() == (60,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_empty_project_catalog_cannot_submit_a_tag_assignment(database: str) -> None:
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("DELETE FROM project_task")
        connection.execute("DELETE FROM project")
    app = dialog(database, "_open_add_project_tag_dialog(service,projects,tags)")
    assert app.warning[0].value == "No projects available."
    assert not app.button and not app.selectbox
    assert create_tag_service(database).get_all_project_tags() == []


def test_group_and_dictionary_dialogs_preserve_reference_guards(database: str) -> None:
    service = create_tag_service(database)
    app = dialog(database, "_open_add_tag_group_dialog(service)")
    app.button[0].click().run()
    assert app.error and not service.get_all_tag_groups()
    app.text_input[0].input("Technology")
    app.button[0].click().run()
    assert not app.exception
    group = service.get_all_tag_groups()[0].id
    app = dialog(database, f"_open_edit_tag_group_dialog(service,{group},'Technology')")
    app.text_input[0].input("Architecture")
    app.button[0].click().run()
    assert (
        not app.exception and service.get_tag_group_by_id(group).tag_group_name == "Architecture"
    )
    app = dialog(database, "_open_add_tag_dialog(service,groups)")
    app.text_input[0].input("Cloud")
    app.selectbox[0].set_value(group)
    app.button[0].click().run()
    assert not app.exception
    tag = service.get_all_tags()[0].id
    blocked = dialog(database, f"_open_delete_tag_group_dialog(service,{group},'Architecture')")
    assert blocked.error and len(blocked.button) == 1
    app = dialog(database, f"_open_edit_tag_dialog(service,{tag},'Cloud',{group},groups)")
    app.text_input[0].input("Cloud native")
    app.button[0].click().run()
    assert not app.exception and service.get_tag_by_id(tag).tag == "Cloud native"
    app = dialog(database, f"_open_delete_tag_dialog(service,{tag},'Cloud native')")
    app.button[0].click().run()
    assert not app.exception and service.get_tag_by_id(tag) is None
    app = dialog(database, f"_open_delete_tag_group_dialog(service,{group},'Architecture')")
    app.button[0].click().run()
    assert not app.exception and service.get_all_tag_groups() == []


def test_project_assignment_dialogs_preserve_combined_and_free_tags(database: str) -> None:
    service = create_tag_service(database)
    tag = service.create_tag(TagDictionary(tag="Priority"))
    app = dialog(database, "_open_add_project_tag_dialog(service,projects,tags)")
    app.selectbox[1].set_value(tag)
    app.text_input[0].input("Urgent")
    app.button[0].click().run()
    assert not app.exception
    assignment = service.get_all_project_tags()[0]
    assert assignment.tag_id == tag and assignment.free_tag == "Urgent"
    app = dialog(
        database,
        f"_open_edit_project_tag_dialog(service,{assignment.id},1,{tag},'Urgent',projects,tags)",
    )
    # Select the rendered empty option; AppTest's raw None means no interaction.
    app.selectbox[1].select_index(0)
    app.text_input[0].input("Reviewed")
    app.button[0].click().run()
    assert not app.exception and service.get_project_tag_by_id(assignment.id).tag_id is None
    app = dialog(database, f"_open_delete_project_tag_dialog(service,{assignment.id},'Reviewed')")
    app.button[0].click().run()
    assert not app.exception and service.get_all_project_tags() == []


def test_task_editor_retains_current_task_outside_search_page_and_deletes(database: str) -> None:
    service = create_tag_service(database)
    assignment = service.create_task_tag(TaskTag(task_id=1, free_tag="Existing"))
    app = dialog(database, f"_open_edit_task_tag_dialog(service,{assignment},1,None,'Existing')")
    assert app.selectbox(key=f"edit_task_tag_{assignment}_task").value == 1
    app.text_input(key=f"edit_task_tag_{assignment}_search").input("Task 60").run()
    assert app.selectbox(key=f"edit_task_tag_{assignment}_task").value == 1
    next(item for item in app.text_input if "Free-form" in item.label).input("Edited")
    app.button[0].click().run()
    assert not app.exception and service.get_task_tag_by_id(assignment).free_tag == "Edited"
    app = dialog(database, f"_open_delete_task_tag_dialog(service,{assignment},'Edited')")
    app.button[0].click().run()
    assert not app.exception and service.get_task_tag_by_id(assignment) is None


def test_dialog_reports_safe_storage_failure_and_concurrent_deletion(database: str) -> None:
    service = create_tag_service(database)
    group = service.create_tag_group(TagGroup(tag_group_name="Transient"))
    app = dialog(database, f"_open_edit_tag_group_dialog(service,{group},'Transient')")
    service.delete_tag_group(group)
    app.button[0].click().run()
    assert not app.exception and app.error and not app.toast
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "CREATE TRIGGER reject_group BEFORE INSERT ON tag_group BEGIN SELECT RAISE(ABORT,'private storage details'); END"
        )
    app = dialog(database, "_open_add_tag_group_dialog(service)")
    app.text_input[0].input("Rejected")
    app.button[0].click().run()
    assert not app.exception and app.error
    assert "private storage details" not in app.error[0].value


@pytest.mark.parametrize(
    ("render", "table", "action", "key"),
    [
        ("render_tag_groups", "_interactive_tag_group_table", "add_tag_group", "tag_groups"),
        ("render_tag_dictionary", "_interactive_tag_dictionary_table", "add_tag", "tags"),
        (
            "render_project_tags",
            "_interactive_project_tag_table",
            "add_project_tag",
            "project_tags",
        ),
        ("render_task_tags", "_interactive_task_tag_table", "add_task_tag", "task_tags"),
    ],
)
def test_catalog_component_routes_create_events_to_migrated_dialogs(
    database: str, render: str, table: str, action: str, key: str
) -> None:
    service = create_tag_service(database)
    group = service.create_tag_group(TagGroup(tag_group_name="Project Tags"))
    tag = service.create_tag(TagDictionary(tag="Priority", tag_group_id=group))
    service.create_project_tag(ProjectTag(project_id=1, tag_id=tag))
    service.create_task_tag(TaskTag(task_id=1, free_tag="Review"))
    with patch(
        f"app.presentation.pages.tags.{table}", return_value={"action": action, "nonce": "create"}
    ) as component:
        app = AppTest.from_string(
            f"""
from app.operator_services import create_tag_service
from app.presentation.pages.tags import {render}
{render}(create_tag_service({database!r}))
""",
            default_timeout=15,
        ).run()
    assert not app.exception, [item.message for item in app.exception]
    assert app.button and component.call_args.kwargs[key]
    if key == "tag_groups":
        assert component.call_args.kwargs[key][0]["tag_count"] == 1
    if key == "tags":
        assert component.call_args.kwargs[key][0]["usage_count"] == 1
