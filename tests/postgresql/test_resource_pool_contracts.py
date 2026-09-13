"""Resource-pool rules, PostgreSQL integrity, atomic use cases, and display projections."""

from app.application.exceptions import ResourcePoolConflictError

from app.presentation.components import resource_pool_frames

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import psycopg
from threading import Barrier

import pytest

from app.application.services.business_access import BusinessAccess
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access

from app.application.exceptions import ResourcePoolStorageError
from app.domain.resources.models import (
    PoolAssignment,
    PoolMapping,
    ResourcePool,
    ResourcePoolGroup,
    ResourcePoolGroupMember,
)
from app.domain.resources.rules import (
    descendant_groups,
    descendant_pools,
    normalize_assignment,
    normalize_group,
    normalize_mapping,
    normalize_pool,
)
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolGateway, PostgresResourcePoolStore
from app.main import create_resource_pool_service


@pytest.fixture
def database(authorized: AuthorizedFixture, runtime: RuntimeResources) -> RuntimeResources:
    """Seed the assignment and tag catalog outside the restricted application role."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='Delivery' WHERE id=1")
        connection.execute(
            "INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date) VALUES(1,1,'Build','2026-09-01','2026-09-03')"
        )
        connection.execute("INSERT INTO eppm.tag_dictionnary(id,tag) VALUES(1,'Priority')")
    return runtime


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), -float("inf")])
def test_pool_values_reject_negative_and_nonfinite_capacity(value: float) -> None:
    for model, normalize in (
        (ResourcePool("Pool", capacity_fte=value), normalize_pool),
        (PoolAssignment(1, 1, value), normalize_assignment),
        (PoolMapping(1, "team", 1, value), normalize_mapping),
    ):
        with pytest.raises(ValueError):
            normalize(model)


def test_group_traversal_terminates_on_cycles_and_deduplicates_shared_pools() -> None:
    members = [
        ResourcePoolGroupMember(1, child_group_id=2),
        ResourcePoolGroupMember(2, child_group_id=1),
        ResourcePoolGroupMember(1, pool_id=3),
        ResourcePoolGroupMember(2, pool_id=3),
    ]
    assert descendant_groups(1, members) == {1, 2}
    assert descendant_pools(1, members) == [3]
    assert descendant_pools(99, members) == []
    assert normalize_mapping(PoolMapping(1, " EMPLOYEE ", 1)).target_type == "employee"
    with pytest.raises(ValueError, match="target"):
        normalize_mapping(PoolMapping(1, "unknown", 1))
    with pytest.raises(ValueError, match="name"):
        normalize_group(ResourcePoolGroup(" "))


def test_pool_and_tags_roll_back_together_on_create_and_edit(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    with pytest.raises(ValueError, match="tag IDs"):
        service.create_pool(ResourcePool("Failed"), tag_ids=[99])
    assert service.get_all_pools() == []
    pool_id = service.create_pool(
        ResourcePool(" Original ", description=" Notes "), tag_ids=[1, 1]
    )
    original = service.get_pool_by_id(pool_id)
    assert original.name == "Original" and original.description == "Notes"
    assert [tag.tag_id for tag in service.get_pool_tags(pool_id)] == [1]
    with pytest.raises(ValueError, match="tag IDs"):
        service.update_pool(replace(original, name="Lost edit"), tag_ids=[99])
    assert service.get_pool_by_id(pool_id) == original
    assert len(service.get_pool_tags(pool_id)) == 1
    assert service.update_pool(replace(original, name="Kept edit"))
    assert len(service.get_pool_tags(pool_id)) == 1
    assert service.update_pool(replace(original, name="Cleared"), tag_ids=[])
    assert service.get_pool_tags(pool_id) == []
    with pytest.raises(ValueError, match="does not exist"):
        service.set_pool_tags(99, [1])


def test_group_details_and_membership_save_or_roll_back_as_one(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    pool_id = service.create_pool(ResourcePool("Pool"))
    child = service.create_pool_group(ResourcePoolGroup("Child"), pool_ids=[pool_id])
    parent = service.create_pool_group(ResourcePoolGroup("Parent"), child_group_ids=[child])
    with pytest.raises(ValueError, match="pool IDs"):
        service.create_pool_group(ResourcePoolGroup("Failed"), pool_ids=[99])
    assert len(service.get_all_pool_groups()) == 2
    original = service.get_pool_group_by_id(child)
    with pytest.raises(ValueError, match="loop"):
        service.update_pool_group(replace(original, name="Lost"), child_group_ids=[parent])
    assert service.get_pool_group_by_id(child) == original
    assert service.get_group_direct_member_ids(child) == ([pool_id], [])
    with pytest.raises(ValueError, match="group IDs"):
        service.replace_group_members(child, [], [99])
    with pytest.raises(ValueError, match="does not exist"):
        service.replace_group_members(99, [], [])
    assert service.get_allowed_child_group_ids(child) == []
    assert service.get_allowed_child_group_ids(parent) == [child]
    assert service.update_pool_group(replace(original, name="Renamed"))
    assert service.get_group_descendant_pool_ids(parent) == [pool_id]
    assert service.update_pool_group(
        replace(original, name="Cleared"), pool_ids=[], child_group_ids=[]
    )
    assert service.get_group_descendant_pool_ids(parent) == []
    assert service.delete_pool_group(child)
    assert service.get_group_direct_member_ids(parent) == ([], [])
    assert service.get_pool_by_id(pool_id) is not None


def test_concurrent_opposite_group_edges_cannot_commit_a_cycle(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    first = service.create_pool_group(ResourcePoolGroup("First"))
    second = service.create_pool_group(ResourcePoolGroup("Second"))
    barrier = Barrier(2)

    def link(parent: int, child: int) -> bool:
        barrier.wait(timeout=5)
        try:
            service.replace_group_members(parent, [], [child])
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(link, first, second), executor.submit(link, second, first)]
        assert sorted(result.result(timeout=10) for result in results) == [False, True]
    assert len(service.get_all_group_members()) == 1


def test_assignment_filters_missing_records_and_mapping_upsert_identity(database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(database, access=access)
    other_service = create_resource_pool_service(database, access=access)
    pool = service.create_pool(ResourcePool("Pool"))
    mapping = PoolMapping(pool, "function", 1)
    first = service.create_mapping(mapping)
    service.create_mapping(replace(mapping, target_id=2))
    assert service.create_mapping(replace(mapping, allocation_pct=20)) == first
    assert service.get_mappings_by_pool(pool)[0].allocation_pct == 20
    assert service.update_mapping(first, 0)
    assert service.delete_mapping(first)
    assignment = PoolAssignment(pool, 1, 0.5, notes=" Notes ")
    project_assignment = service.create_assignment(assignment)
    task_assignment = service.create_assignment(replace(assignment, task_id=1))
    assert service.get_assignment_by_id(task_assignment).notes == "Notes"
    assert service.update_assignment(
        replace(assignment, id=task_assignment, task_id=1, fte_assigned=0.75)
    )
    assert [row["id"] for row in service.get_assignments(task_id=1)] == [task_assignment]
    assert [
        row["id"] for row in service.get_assignments(project_id=1, only_project_level=True)
    ] == [project_assignment]
    assert service.get_task_assignments_map([1])[1][0]["fte"] == 0.75
    assert service.get_project_assignments_map([1])[1][0]["id"] == project_assignment
    assert service.get_task_assignments_map([]) == service.get_project_assignments_map([]) == {}
    assert service.delete_assignment(task_assignment)
    assert service.get_assignment_by_id(task_assignment) is None
    assert not service.update_pool(ResourcePool("Missing"))
    assert not service.update_pool(ResourcePool("Missing", id=99), tag_ids=[1])
    assert not service.update_pool_group(ResourcePoolGroup("Missing"))
    assert not service.update_pool_group(ResourcePoolGroup("Missing", id=99), pool_ids=[pool])
    assert not service.update_assignment(assignment)
    assert not service.update_assignment(replace(assignment, id=99))
    assert not service.delete_pool_group(99)
    assert service.get_pool_group_by_id(99) is None
    assert not service.delete_mapping(99)
    assert not service.delete_assignment(99)
    assert not service.update_mapping(99, 0)
    assert list(resource_pool_frames.pools_frame(other_service.get_all_pools())["id"]) == [pool]
    assert service.delete_pool(pool)
    assert resource_pool_frames.assignments_frame(other_service.get_assignments()).empty and resource_pool_frames.mappings_frame(other_service.get_all_mappings()).empty


def test_gateway_rolls_back_reuses_the_pool_and_allows_an_independent_writer(
    database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    """Application and database failures roll back while retaining usable leases."""
    gateway = PostgresResourcePoolGateway(database.database, database.key, access=access)

    def fail_after_write(store: PostgresResourcePoolStore) -> None:
        store.create_pool(ResourcePool("Rolled back"))
        with psycopg.connect(authorized.setup.operator_url) as contender:
            contender.execute("SET LOCAL statement_timeout='1s'")
            contender.execute("UPDATE eppm.project SET name='Independent' WHERE id=2")
        raise ValueError("abort")

    with pytest.raises(ValueError, match="abort"):
        gateway.run(fail_after_write, write=True)
    assert gateway.run(lambda store: store.get_all_pools()) == []
    assert authorized.query('SELECT name FROM eppm.project WHERE id=2', user_id=4) == [('Independent',)]
    with pytest.raises(ResourcePoolConflictError) as failure:
        gateway.run(lambda store: store.create_assignment(PoolAssignment(99, 1, 1)), write=True)
    assert failure.value.__cause__ is None
    with pytest.raises(ResourcePoolStorageError, match="could not be accessed") as failure:
        gateway.run(lambda store: store.connection.execute('SELECT * FROM eppm.missing_table'))
    assert "missing_table" not in str(failure.value)
    with pytest.raises(ResourcePoolConflictError):
        create_resource_pool_service(database, access=access).create_assignment(PoolAssignment(99, 1, 1))
    assert gateway.run(lambda store: store.get_all_pools()) == []
