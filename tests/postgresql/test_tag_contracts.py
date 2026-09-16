"""Tag use cases, transaction guarantees, typed projections, and safe errors."""

from app.application.exceptions import TagConflictError

from dataclasses import replace
from unittest.mock import patch

import psycopg
import pytest

from app.application.exceptions import TagStorageError
from app.domain.access.models import AccessDenied
from app.domain.tags.models import ProjectTag, ResourcePoolTag, TagDictionary, TagGroup, TaskTag
from app.domain.tags.rules import (
    normalize_group,
    normalize_project_tag,
    normalize_tag,
    normalize_task_tag,
    validate_assignment,
)
from app.application.services.business_access import BusinessAccess
from app.infrastructure.postgresql.tags import PostgresTagGateway, PostgresTagStore
from app.main import create_tag_service
from app.runtime import RuntimeResources
from tests.postgresql.ui import runtime as runtime, access as access


@pytest.fixture
def database(authorized, runtime: RuntimeResources) -> RuntimeResources:
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='Project' WHERE id=1")
        connection.execute(
            "INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (1,1,'Build','2026-09-01','2026-09-03',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))"
        )
        connection.execute("INSERT INTO eppm.resource_pool(id,name) VALUES(1,'Pool')")
    return runtime


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
    database: RuntimeResources, access: BusinessAccess,
) -> None:
    service = create_tag_service(database, access=access)
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
    database: RuntimeResources, access: BusinessAccess, authorized,
) -> None:
    service = create_tag_service(database, access=access)
    tag = service.create_tag(TagDictionary(tag="Protected"))
    project_tag = service.create_project_tag(ProjectTag(project_id=1, tag_id=tag))
    task_tag = service.create_task_tag(TaskTag(task_id=1, tag_id=tag))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_tag_delete() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'internal trigger details' USING ERRCODE='23514'; END $$""")
        connection.execute("""CREATE TRIGGER reject_tag_delete BEFORE DELETE ON eppm.tag_dictionnary
            FOR EACH ROW EXECUTE FUNCTION eppm.reject_tag_delete()""")
    with pytest.raises(TagConflictError) as failure:
        service.delete_tag(tag)
    assert "internal trigger details" not in str(failure.value)
    assert service.get_project_tag_by_id(project_tag) is not None
    assert service.get_task_tag_by_id(task_tag) is not None


def test_assignment_foreign_keys_and_missing_record_results(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_tag_service(database, access=access)
    with pytest.raises(AccessDenied):
        service.create_project_tag(ProjectTag(project_id=99, free_tag="Missing"))
    with pytest.raises(TagConflictError):
        service.create_task_tag(TaskTag(task_id=1, tag_id=99))
    with pytest.raises(AccessDenied):
        create_tag_service(database, access=access).create_task_tag(TaskTag(task_id=99, free_tag="Legacy"))
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


def test_gateway_rolls_back_tag_writes_releases_leases_and_allows_an_independent_writer(database: RuntimeResources, access: BusinessAccess, authorized) -> None:
    gateway = PostgresTagGateway(database.database, database.key, access=access)

    def fail_after_write(store):
        store.create_tag_group(TagGroup(tag_group_name='Rolled back'))
        with psycopg.connect(authorized.setup.operator_url) as contender:
            contender.execute("SET LOCAL statement_timeout='1s'")
            contender.execute("UPDATE eppm.project SET name='Independent writer' WHERE id=2")
        raise ValueError('rollback')

    with pytest.raises(ValueError, match="rollback"):
        gateway.run(fail_after_write, write=True)
    assert gateway.run(lambda store: store.get_all_tag_groups()) == []
    assert authorized.query('SELECT name FROM eppm.project WHERE id=2', user_id=4) == [('Independent writer',)]
    with pytest.raises(TagStorageError) as failure:
        gateway.run(lambda store: store.connection.execute('SELECT * FROM eppm.missing_table'))
    assert "missing_table" not in str(failure.value)
    assert gateway.run(lambda store: store.get_all_tag_groups()) == []


def test_bounded_task_lookup_and_project_choices_use_plain_records(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_tag_service(database, access=access)
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
    database: RuntimeResources, access: BusinessAccess, query: dict
) -> None:
    with pytest.raises(ValueError, match="Invalid tag"):
        create_tag_service(database, access=access).get_task_tags_page(**query)


def test_page_counts_and_rows_share_one_snapshot_during_concurrent_write(database: RuntimeResources, access: BusinessAccess, authorized) -> None:
    service = create_tag_service(database, access=access)
    service.create_task_tag(TaskTag(task_id=1, free_tag="Match"))
    changed = False
    read_rows = PostgresTagStore._rows

    def insert_between_counts_and_rows(store, model, query, parameters=()):
        nonlocal changed
        if not changed and 'FROM eppm.task_tag tt' in query:
            changed = True
            with psycopg.connect(authorized.setup.operator_url) as writer:
                writer.execute("INSERT INTO eppm.task_tag(task_id,free_tag) VALUES(1,'Match')")
        return read_rows(store, model, query, parameters)

    with patch.object(PostgresTagStore, '_rows', insert_between_counts_and_rows):
        page = service.get_task_tags_page(search="Match")
    assert changed
    assert (page.total, page.filtered_total, len(page.rows)) == (1, 1, 1)
    assert service.get_task_tags_page().total == 2
