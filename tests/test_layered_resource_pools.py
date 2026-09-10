"""Resource-pool rules, SQLite integrity, atomic use cases, and display projections."""

from app.operator_services import deployment_access
from app.application.exceptions import ResourcePoolConflictError

from app.presentation.components import resource_pool_frames

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest

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
from app.infrastructure.repositories.resource_pools import SqliteResourcePoolGateway
from app.operator_services import create_resource_pool_service
from app.infrastructure.database.schema_init import init_db


@pytest.fixture
def database(tmp_path: Path) -> str:
    """Create the real existing schema with a minimal assignment/tag catalog."""
    path = str(tmp_path / "pools.db")
    init_db(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("INSERT INTO project(id,name) VALUES(1,'Delivery')")
        connection.execute(
            "INSERT INTO project_task(id,project_id,task_name,start_date,end_date) VALUES(1,1,'Build','2026-09-01','2026-09-03')"
        )
        connection.execute("INSERT INTO tag_dictionnary(id,tag) VALUES(1,'Priority')")
    return path


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


def test_pool_and_tags_roll_back_together_on_create_and_edit(database: str) -> None:
    service = create_resource_pool_service(database)
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


def test_group_details_and_membership_save_or_roll_back_as_one(database: str) -> None:
    service = create_resource_pool_service(database)
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


def test_concurrent_opposite_group_edges_cannot_commit_a_cycle(database: str) -> None:
    service = create_resource_pool_service(database)
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


def test_assignment_filters_missing_records_and_mapping_upsert_identity(database: str) -> None:
    service = create_resource_pool_service(database)
    other_service = create_resource_pool_service(database)
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


def test_gateway_reserves_writes_rolls_back_and_closes_connections(database: str) -> None:
    gateway = SqliteResourcePoolGateway(database, access=deployment_access())
    with pytest.raises(ValueError, match="abort"):
        with gateway.transaction(write=True) as store:
            connection = store.connection
            store.create_pool(ResourcePool("Rolled back"))
            with closing(sqlite3.connect(database, timeout=0)) as contender:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    contender.execute("BEGIN IMMEDIATE")
            raise ValueError("abort")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with gateway.transaction() as store:
        assert store.get_all_pools() == []
        connection = store.connection
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with pytest.raises(ResourcePoolConflictError) as failure:
        with gateway.transaction(write=True) as store:
            store.create_assignment(PoolAssignment(99, 1, 1))
    assert isinstance(failure.value.__cause__, sqlite3.IntegrityError)
    with pytest.raises(ResourcePoolStorageError, match="could not be accessed") as failure:
        with gateway.transaction() as store:
            store.connection.execute("SELECT * FROM missing_table")
    assert "missing_table" not in str(failure.value)
    with pytest.raises(ResourcePoolConflictError):
        create_resource_pool_service(database).create_assignment(PoolAssignment(99, 1, 1))
