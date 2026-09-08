"""Tag use cases, transaction guarantees, typed projections, and safe errors."""

from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from app.application.exceptions import TagConflictError, TagStorageError
from app.domain.tags.models import ProjectTag, ResourcePoolTag, TagDictionary, TagGroup, TaskTag
from app.domain.tags.rules import (
    normalize_group,
    normalize_project_tag,
    normalize_tag,
    normalize_task_tag,
    validate_assignment,
)
from app.infrastructure.repositories.tags import SqliteTagGateway
from app.infrastructure.database.connection import get_db
from app.main import create_tag_service
from src.database.schema_init import init_db
from src.repositories.tag_repo import TagRepository


@pytest.fixture
def database(tmp_path: Path) -> str:
    path = str(tmp_path / "tags.db")
    init_db(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("INSERT INTO project(id,name) VALUES(1,'Project')")
        connection.execute(
            "INSERT INTO project_task(id,project_id,task_name,start_date,end_date) VALUES(1,1,'Build','2026-09-01','2026-09-03')"
        )
        connection.execute("INSERT INTO resource_pool(id,name) VALUES(1,'Pool')")
    return path


def test_tag_domain_preserves_combined_assignments_and_optional_group_validation() -> None:
    assert normalize_group(TagGroup(tag_group_name=" Group ")).tag_group_name == "Group"
    assert normalize_tag(TagDictionary(tag=" Label ")).tag == "Label"
    assert (
        normalize_project_tag(ProjectTag(project_id=1, tag_id=1, free_tag=" Both ")).free_tag
        == "Both"
    )
    assert normalize_task_tag(TaskTag(task_id=1, tag_id=1, free_tag=" ")).free_tag is None
    with pytest.raises(ValueError, match="group name"):
        normalize_group(TagGroup(tag_group_name=" "))
    with pytest.raises(ValueError, match="Tag name"):
        normalize_tag(TagDictionary(tag=" "))
    for normalize, tag in (
        (normalize_project_tag, ProjectTag(project_id=1)),
        (normalize_task_tag, TaskTag(task_id=1)),
    ):
        with pytest.raises(ValueError, match="Dictionary Tag"):
            normalize(tag)
    validate_assignment(
        1, 2, None, entity="Project", group=TagGroup(tag_group_name="Project Tags")
    )
    with pytest.raises(ValueError, match="mandatory"):
        validate_assignment(0, 2, None, entity="Task")
    with pytest.raises(ValueError, match="Task_Tag"):
        validate_assignment(
            1, 2, None, entity="Task", group=TagGroup(tag_group_name="Project Tags")
        )


def test_typed_catalogs_count_all_assignment_kinds_and_keep_cross_group_contract(
    database: str,
) -> None:
    service = create_tag_service(database)
    group = service.create_tag_group(TagGroup(tag_group_name="Business classification"))
    tag = service.create_tag(TagDictionary(tag="Critical", tag_group_id=group))
    project_tag = service.create_project_tag(ProjectTag(project_id=1, tag_id=tag))
    task_tag = service.create_task_tag(TaskTag(task_id=1, tag_id=tag, free_tag="Urgent"))
    pool_tag = service.create_resource_pool_tag(ResourcePoolTag(pool_id=1, tag_id=tag))
    assert service.get_all_tag_groups()[0].tag_count == 1
    assert service.get_all_tags()[0].usage_count == service.count_tag_usages(tag) == 3
    assert service.get_all_project_tags()[0].project_name == "Project"
    assert service.get_all_task_tags()[0].task_name == "Build"
    assert service.get_all_resource_pool_tags()[0].pool_name == "Pool"
    assert service.get_project_tags_by_project(1)[0].tag_name == "Critical"
    assert service.get_task_tags_by_task(1)[0].free_tag == "Urgent"
    assert service.get_resource_pool_tags(1)[0].tag_id == tag
    assert service.create_resource_pool_tag(ResourcePoolTag(pool_id=1, tag_id=tag)) == pool_tag
    with pytest.raises(ValueError, match="dictionary tags"):
        service.delete_tag_group(group)
    assert service.delete_resource_pool_tag(pool_tag)
    assert service.delete_tag(tag)
    assert service.get_project_tag_by_id(project_tag) is None
    assert service.get_task_tag_by_id(task_tag) is None
    assert service.delete_tag_group(group)


def test_dictionary_deletion_rolls_back_earlier_assignment_deletes_on_failure(
    database: str,
) -> None:
    service = create_tag_service(database)
    tag = service.create_tag(TagDictionary(tag="Protected"))
    project_tag = service.create_project_tag(ProjectTag(project_id=1, tag_id=tag))
    task_tag = service.create_task_tag(TaskTag(task_id=1, tag_id=tag))
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "CREATE TRIGGER reject_tag_delete BEFORE DELETE ON tag_dictionnary BEGIN SELECT RAISE(ABORT,'internal trigger details'); END"
        )
    with pytest.raises(TagConflictError) as failure:
        service.delete_tag(tag)
    assert "internal trigger details" not in str(failure.value)
    assert isinstance(failure.value.__cause__, sqlite3.IntegrityError)
    assert service.get_project_tag_by_id(project_tag) is not None
    assert service.get_task_tag_by_id(task_tag) is not None


def test_assignment_foreign_keys_and_missing_record_results(database: str) -> None:
    service = create_tag_service(database)
    with pytest.raises(TagConflictError):
        service.create_project_tag(ProjectTag(project_id=99, free_tag="Missing"))
    with pytest.raises(TagConflictError):
        service.create_task_tag(TaskTag(task_id=1, tag_id=99))
    with pytest.raises(sqlite3.IntegrityError):
        TagRepository(database).create_task_tag(TaskTag(task_id=99, free_tag="Legacy"))
    for model, update in (
        (TagGroup(tag_group_name="Missing"), service.update_tag_group),
        (TagDictionary(tag="Missing"), service.update_tag),
        (ProjectTag(project_id=1, free_tag="Missing"), service.update_project_tag),
        (TaskTag(task_id=1, free_tag="Missing"), service.update_task_tag),
    ):
        assert not update(model)
        assert not update(replace(model, id=99))
    assert not service.delete_resource_pool_tag(99)
    assert service.get_task_choice(99) is None
    assert service.get_task_tags_by_task_ids([]) == {}
    assert service.get_project_tags_by_project_ids([]) == {}


def test_gateway_reserves_writes_and_closes_connections_on_every_exit(database: str) -> None:
    gateway = SqliteTagGateway(database)
    with pytest.raises(ValueError, match="rollback"):
        with gateway.transaction(write=True) as store:
            connection = store.connection
            store.create_tag_group(TagGroup(tag_group_name="Rolled back"))
            with closing(sqlite3.connect(database, timeout=0)) as contender:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    contender.execute("BEGIN IMMEDIATE")
            raise ValueError("rollback")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with gateway.transaction() as store:
        assert store.get_all_tag_groups() == []
        connection = store.connection
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with pytest.raises(TagStorageError) as failure:
        with gateway.transaction() as store:
            store.connection.execute("SELECT * FROM missing_table")
    assert "missing_table" not in str(failure.value)


def test_bounded_task_lookup_and_project_choices_use_plain_records(database: str) -> None:
    service = create_tag_service(database)
    assert service.project_choices()[0].name == "Project"
    assert service.search_task_choices("#1")[0] == service.get_task_choice(1)
    assert service.search_task_choices("Project")[0].task_name == "Build"
    assert service.search_task_choices("' OR 1=1 --") == []
    assert service.get_task_tags_page().rows == []


@pytest.mark.parametrize(
    "query",
    [
        dict(page=None),
        dict(page_size=float("inf")),
        dict(search=[]),
        dict(sort={}),
        dict(filters=[]),
    ],
)
def test_invalid_component_page_queries_raise_safe_application_errors(
    database: str, query: dict
) -> None:
    with pytest.raises(ValueError, match="Invalid tag"):
        create_tag_service(database).get_task_tags_page(**query)


def test_page_counts_and_rows_share_one_snapshot_during_concurrent_write(database: str) -> None:
    service = create_tag_service(database)
    service.create_task_tag(TaskTag(task_id=1, free_tag="Match"))
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    changed = False

    def connect(path: str) -> sqlite3.Connection:
        connection = get_db(path)

        def trace(sql: str) -> None:
            nonlocal changed
            if not changed and "LEFT JOIN project_task" in sql:
                changed = True
                with closing(sqlite3.connect(path)) as writer, writer:
                    writer.execute("INSERT INTO task_tag(task_id,free_tag) VALUES(1,'Match')")

        connection.set_trace_callback(trace)
        return connection

    with patch("app.infrastructure.repositories.tags.get_db", connect):
        page = service.get_task_tags_page(search="Match")
    assert (page.total, page.filtered_total, len(page.rows)) == (1, 1, 1)
    assert service.get_task_tags_page().total == 2
