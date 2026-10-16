"""Real PostgreSQL migration, authorization, hierarchy, and pool-type integrity."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import psycopg
import pytest

from app.application.exceptions import ResourcePoolConflictError
from app.domain.access.models import AccessDenied
from app.domain.resources.models import ResourcePool
from app.domain.resources.pool_types import PoolType
from app.infrastructure.postgresql.migration import discover_migrations, migrate
from tests.postgresql.test_resource_pools import service


def test_upgrade_maps_existing_pools_to_human_and_keeps_their_data(empty_database, tmp_path):
    migrations = discover_migrations()
    for item in migrations[:38]:
        (tmp_path/item.name).write_bytes(item.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        identity = connection.execute("INSERT INTO eppm.resource_pool(name,capacity_fte) VALUES ('Existing',3.5) RETURNING id").fetchone()[0]
    assert migrate(empty_database.operator_url) == tuple(item.name for item in migrations[38:])
    assert migrate(empty_database.operator_url) == ()
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute('SELECT id,name,capacity_fte,pool_type_id FROM eppm.resource_pool').fetchall() == [(identity,'Existing',3.5,1)]
        assert connection.execute('SELECT id,name,parent_pool_type_id FROM eppm.pool_type ORDER BY id').fetchall() == [(1,'Human',None),(2,'Car',None)]


def test_catalog_and_pool_type_assignments_round_trip(authorized):
    pools = service(authorized)
    assert [(row.id,row.name) for row in pools.get_all_pool_types()] == [(1,'Human'),(2,'Car')]
    van = pools.save_pool_type(PoolType('Van', parent_pool_type_id=2, translations={'fr':'Camionnette'}))
    pool_id = pools.create_pool(ResourcePool('Fleet', pool_type_id=van))
    assert pools.get_pool_by_id(pool_id).pool_type_id == van
    record = next(row for row in pools.get_all_pool_types() if row.id == van)
    assert record.parent_pool_type_id == 2 and record.label('fr') == 'Camionnette'
    assert pools.update_pool(replace(pools.get_pool_by_id(pool_id), pool_type_id=1))
    assert pools.get_all_pools()[0].pool_type_id == 1
    pools.save_pool_type(replace(record, name='Minibus', parent_pool_type_id=None))
    assert pools.get_all_pool_types()[-1].name == 'Minibus'
    assert pools.delete_pool_type(van)


def test_database_rejects_null_and_missing_pool_types(authorized):
    for value, error in [(None,psycopg.errors.NotNullViolation),(9999,psycopg.errors.ForeignKeyViolation)]:
        with psycopg.connect(authorized.setup.operator_url) as connection:
            with pytest.raises(error):
                connection.execute('INSERT INTO eppm.resource_pool(name,pool_type_id) VALUES (%s,%s)', ('Invalid',value))
    with pytest.raises(ResourcePoolConflictError):
        service(authorized).create_pool(ResourcePool('Missing', pool_type_id=9999))


def test_referenced_types_cannot_be_deleted_and_cycles_are_rejected(authorized):
    pools = service(authorized)
    child = pools.save_pool_type(PoolType('Child', parent_pool_type_id=2))
    identity = pools.create_pool(ResourcePool('Fleet', pool_type_id=child))
    for value in (2,child):
        with pytest.raises(ResourcePoolConflictError):
            pools.delete_pool_type(value)
    for target,parent in [(2,child),(2,2)]:
        with psycopg.connect(authorized.setup.operator_url) as connection:
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute('UPDATE eppm.pool_type SET parent_pool_type_id=%s WHERE id=%s',(parent,target))
    with pytest.raises(ValueError, match='circular'):
        pools.save_pool_type(PoolType('Car',id=2,parent_pool_type_id=child))
    assert pools.get_pool_by_id(identity).pool_type_id == child


def test_duplicate_name_rolls_back_parent_and_translations(authorized):
    pools = service(authorized)
    with pytest.raises(ResourcePoolConflictError):
        pools.save_pool_type(PoolType('Human',id=2,parent_pool_type_id=1,translations={'fr':'Changed'}))
    car = pools.get_all_pool_types()[1]
    assert car.name == 'Car' and car.parent_pool_type_id is None and car.label('fr') == 'Voiture'


def test_type_management_requires_shared_permission_at_both_boundaries(authorized):
    with pytest.raises(AccessDenied):
        service(authorized,1).save_pool_type(PoolType('Denied'))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query("INSERT INTO eppm.pool_type(name) VALUES ('Denied')",user_id=1,write=True)


def test_concurrent_opposite_parent_links_cannot_commit_a_cycle(authorized):
    pools = service(authorized)
    first,second = [pools.save_pool_type(PoolType(name)) for name in ('First','Second')]
    def link(child,parent):
        try:
            service(authorized).save_pool_type(PoolType(str(child),id=child,parent_pool_type_id=parent))
            return True
        except (ValueError,ResourcePoolConflictError):
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(link,first,second),executor.submit(link,second,first)]
        assert sorted(f.result(timeout=20) for f in futures) == [False,True]
