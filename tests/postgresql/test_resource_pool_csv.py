"""Atomic CSV upserts preserve identities, history and pool hierarchy rules."""

from dataclasses import replace

import psycopg
import pytest

from app.application.services.resource_pool_csv import export_pools, parse_pools
from app.application.exceptions import ResourcePoolConflictError
from app.domain.access.models import AccessDenied
from app.domain.resources.models import PoolAssignment, PoolCapacityException, ResourcePool
from tests.postgresql.test_resource_pools import service


def test_import_updates_known_ids_generates_unknown_ids_and_remaps_new_parents(authorized):
    pools = service(authorized)
    known = pools.create_pool(ResourcePool('Existing', capacity_fte=2))
    original = pools.get_pool_by_id(known)
    pools.save_capacity_exception(PoolCapacityException(known, '2026-01-01', '2026-01-02', 1))
    result = pools.import_csv(export_pools([
        ResourcePool('Child', id=800001, parent_pool_id=800000, capacity_fte=3),
        ResourcePool('Parent', id=800000, capacity_fte=12),
        replace(original, name='Updated', capacity_fte=4),
        ResourcePool('Without ID', deleted_flag=True),
    ]).encode())
    assert (result.created, result.updated) == (3, 1)
    rows = {row.name: row for row in pools.get_all_pools(include_deleted=True)}
    assert rows['Updated'].id == known
    assert rows['Updated'].created_at == original.created_at
    assert rows['Updated'].capacity_fte == 4
    assert rows['Child'].parent_pool_id == rows['Parent'].id
    assert rows['Parent'].capacity_fte == 0
    assert not {800000, 800001} & {row.id for row in rows.values()}
    assert rows['Without ID'].deleted_flag
    assert len(pools.capacity_exceptions(known)) == 1
    assert pools.create_pool(ResourcePool('Next')) > max(row.id for row in rows.values())


def test_export_visibility_and_csv_deletion_restore_preserve_allocations(authorized):
    pools = service(authorized)
    identity = pools.create_pool(ResourcePool('Pool', capacity_fte=2))
    assignment = pools.create_assignment(PoolAssignment(identity, 1, 1))
    original = pools.get_pool_by_id(identity)
    result = pools.import_csv(export_pools([replace(original, name='Deleted', deleted_flag=True)]).encode())
    assert (result.created, result.updated) == (0, 1)
    assert parse_pools(pools.export_csv(include_deleted=True).encode())[0].deleted_flag
    assert 'Deleted' not in pools.export_csv()
    assert pools.get_assignments(pool_id=identity) == []
    pools.import_csv(export_pools([replace(original, name='Restored')]).encode())
    assert pools.get_pool_by_id(identity).name == 'Restored'
    assert pools.get_assignments(pool_id=identity)[0]['id'] == assignment


@pytest.mark.parametrize('kind', ['cycle', 'unknown_parent', 'deleted_parent', 'assigned_parent', 'exception_parent'])
def test_invalid_hierarchy_rolls_back_the_entire_import(authorized, kind):
    pools = service(authorized)
    parent = pools.create_pool(ResourcePool('Parent', capacity_fte=4))
    original = pools.get_pool_by_id(parent)
    child = ResourcePool('New child', id=900000, parent_pool_id=parent)
    changed = replace(original, name='Must roll back')
    if kind == 'cycle':
        changed = replace(changed, parent_pool_id=900000)
    elif kind == 'unknown_parent':
        child = replace(child, parent_pool_id=900001)
    elif kind == 'deleted_parent':
        changed = replace(changed, deleted_flag=True)
    elif kind == 'assigned_parent':
        pools.create_assignment(PoolAssignment(parent, 1, 1))
    else:
        pools.save_capacity_exception(PoolCapacityException(parent, '2026-01-01', '2026-01-02', 1))
    with pytest.raises(ValueError):
        pools.import_csv(export_pools([changed, child]).encode())
    assert pools.get_all_pools(include_deleted=True) == [original]


def test_deleted_hierarchy_round_trip_and_out_of_order_restoration(authorized):
    pools = service(authorized)
    parent = pools.create_pool(ResourcePool('Parent'))
    child = pools.create_pool(ResourcePool('Child', parent_pool_id=parent))
    rows = pools.get_all_pools()
    pools.import_csv(export_pools([replace(row, deleted_flag=True) for row in rows]).encode())
    deleted = pools.export_csv(include_deleted=True)
    pools.import_csv(deleted.encode())
    assert pools.get_all_pools() == []
    pools.import_csv(export_pools(rows).encode())
    assert pools.get_pool_by_id(child).parent_pool_id == parent


def test_csv_cannot_restore_a_mapped_pool_as_container(authorized):
    pools = service(authorized)
    identity = pools.create_pool(ResourcePool('Mapped'))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.team(team_id,team_name) VALUES (1,'Team')")
        connection.execute("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id) VALUES (%s,'team',1)", (identity,))
    original = pools.get_pool_by_id(identity)
    pools.delete_pool(identity)
    with pytest.raises(ValueError, match='container'):
        pools.import_csv(export_pools([original, ResourcePool('Child', parent_pool_id=identity)]).encode())
    assert pools.get_all_pools() == []
    assert len(pools.get_all_pools(include_deleted=True)) == 1


def test_csv_write_requires_shared_management_permission(authorized):
    with pytest.raises(AccessDenied):
        service(authorized, user_id=2).import_csv(b'name\nForbidden\n')
    assert service(authorized).get_all_pools() == []


def test_missing_id_column_creates_new_records_and_database_errors_roll_back(authorized):
    pools = service(authorized)
    result = pools.import_csv(b'name\nFirst\nSecond\n')
    assert (result.created, result.updated) == (2, 0)
    original = pools.get_all_pools()
    with pytest.raises(ResourcePoolConflictError):
        pools.import_csv(export_pools([
            replace(original[0], name='Changed'),
            ResourcePool('Invalid reference', pool_type_id=999999),
        ]).encode())
    assert pools.get_all_pools() == original
