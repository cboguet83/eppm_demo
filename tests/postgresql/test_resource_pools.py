"""Native pool workflows, scoped assignments and complete concurrent callbacks."""

from tests.postgresql.pool_helpers import create_container

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from threading import Barrier, Event

import psycopg
import pytest

from app.application.exceptions import ResourcePoolConflictError, ResourcePoolStorageError
from app.application.services.resource_pools import ResourcePoolService
from app.domain.access.models import AccessDenied
from app.domain.resources.models import PoolAssignment, PoolMapping, ResourcePool
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolGateway


def gateway(authorized, user_id=4):
    return PostgresResourcePoolGateway(authorized.database, authorized.key, access=authorized.binding(user_id).access)


def service(authorized, user_id=4):
    return ResourcePoolService(gateway(authorized, user_id))


@pytest.fixture
def pools(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.team(team_id,team_name) VALUES (1,'Team'),(10,'Mapping team')")
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level) VALUES (10,'Mapping function',1)")
        connection.execute("INSERT INTO eppm.employee(employee_id,firstname,lastname,email,employee_code) VALUES (10,'Mapping','Employee','mapping@example.test','MAPPING')")
        connection.execute("INSERT INTO eppm.hierarchy_type(code) VALUES ('service')")
        connection.execute("INSERT INTO eppm.hierarchy_type_translation VALUES (1,'fr','Service')")
        connection.execute("INSERT INTO eppm.tag_group(tag_group_name) VALUES ('Priority')")
        connection.execute("INSERT INTO eppm.tag_dictionnary(tag,tag_group_id) VALUES ('High',1),('Low',NULL)")
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (11,1,'Visible','2026-01-01','2026-01-05',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(12,2,'Read only','2026-02-01','2026-02-05',(SELECT id FROM eppm.project_plan WHERE project_id=2 AND is_current)),(13,3,'Private','2026-03-01','2026-03-05',(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))")
    return service(authorized)


def test_pool_details_tags_and_hierarchy_are_atomic_and_identity_is_stable(pools, authorized):
    assert pools.get_all_hierarchy_types()[0].translations == {'fr': 'Service'}
    identity = pools.create_pool(ResourcePool(' Original ', description=' Notes ', hierarchy_type_id=1), tag_ids=[1, 1])
    original = pools.get_pool_by_id(identity)
    assert original.name == 'Original' and original.description == 'Notes' and original.capacity_fte is None
    assert original.hierarchy_type_id == 1 and original.created_at
    assert [(tag.tag_id, tag.tag_group_name) for tag in pools.get_pool_tags(identity)] == [(1, 'Priority')]
    with pytest.raises(ValueError, match='tag IDs'):
        pools.update_pool(replace(original, name='Lost', capacity_fte=7), tag_ids=[999])
    assert pools.get_pool_by_id(identity) == original
    with pytest.raises(ValueError, match='tag IDs'):
        pools.create_pool(ResourcePool('Lost'), tag_ids=[999])
    assert len(pools.get_all_pools()) == 1
    assert pools.update_pool(replace(original, name='Kept', capacity_fte=0, hierarchy_type_id=None), tag_ids=[2])
    kept = pools.get_pool_by_id(identity)
    assert kept.created_at == original.created_at and kept.capacity_fte == 0 and kept.hierarchy_type_id is None
    assert pools.get_pool_tags(identity)[0].tag_group_name is None
    pools.set_pool_tags(identity, [])
    assert pools.get_pool_tags(identity) == []
    with pytest.raises(ResourcePoolConflictError):
        pools.create_pool(ResourcePool('Kept'))
    with pytest.raises(ValueError, match='no longer exists'):
        pools.update_pool(replace(kept, hierarchy_type_id=999))
    with pytest.raises(ValueError, match='does not exist'):
        pools.set_pool_tags(999, [1])
    assert pools.get_pool_by_id(identity) == kept
    assert not pools.update_pool(ResourcePool('Absent'))
    assert not pools.update_pool(ResourcePool('Absent', id=999), tag_ids=[1])
    assert pools.get_pool_by_id(999) is None and not pools.delete_pool(999)
    assert [row.id for row in service(authorized, 1).pool_choices()] == [identity]


def test_recursive_pools_resolve_leaves_and_reparent_without_changing_identity(pools, authorized):
    root = pools.create_pool(ResourcePool('Root'))
    branch = pools.create_pool(ResourcePool('Branch', parent_pool_id=root, hierarchy_type_id=1))
    leaf = pools.create_pool(ResourcePool('Leaf', parent_pool_id=branch))
    original = pools.get_pool_by_id(branch)
    assert pools.descendant_pool_ids(root) == [leaf]
    with pytest.raises(ValueError, match='circular'):
        pools.update_pool(replace(original, parent_pool_id=leaf, name='Lost'))
    assert pools.get_pool_by_id(branch) == original
    with pytest.raises(ValueError, match='parent pool'):
        pools.update_pool(replace(original, parent_pool_id=999))
    assert pools.update_pool(replace(original, parent_pool_id=None))
    assert pools.get_pool_by_id(branch).created_at == original.created_at
    assert pools.delete_pool(root)
    assert pools.get_pool_by_id(branch) and pools.get_pool_by_id(leaf)


def test_mapping_upsert_retains_identity_and_all_target_kinds(pools):
    pool = pools.create_pool(ResourcePool('Pool'))
    identities = [pools.create_mapping(PoolMapping(pool, kind, 10, 50)) for kind in (' TEAM ', 'employee', 'function')]
    assert pools.create_mapping(PoolMapping(pool, 'team', 10, 25)) == identities[0]
    assert [row.target_type for row in pools.get_mappings_by_pool(pool)] == ['employee', 'function', 'team']
    assert pools.update_mapping(identities[0], 0)
    assert len(pools.get_all_mappings()) == 3
    assert pools.get_mappings_by_pool(pool)[-1].allocation_pct == 0
    assert pools.delete_mapping(identities[1]) and not pools.delete_mapping(999)
    assert not pools.update_mapping(999, 0)
    pools.delete_pool(pool)
    assert pools.get_all_mappings() == []


def test_assignment_filters_native_dates_and_batched_links_respect_project_scope(pools, authorized):
    pool = pools.create_pool(ResourcePool('Pool'))
    admin_ids = [pools.create_assignment(PoolAssignment(pool, project, 0.5, task_id=10 + project)) for project in (1, 2, 3)]
    direct = [pools.create_assignment(PoolAssignment(pool, project, 0.25)) for project in (1, 2, 3)]
    reader = service(authorized, 1)
    assert [row['id'] for row in reader.get_assignments(pool_id=pool)] == [direct[0], admin_ids[0], direct[1], admin_ids[1]]
    assert [row['id'] for row in reader.get_assignments(project_id=2, only_project_level=True, task_id=12)] == [direct[1]]
    row = reader.get_assignments(task_id=11)[0]
    assert row['effective_start_date'] == row['task_start_date'] == '2026-01-01'
    assert row['effective_end_date'] == row['task_end_date'] == '2026-01-05'
    assert row['custom_start_date'] is None
    original = reader.get_assignment_by_id(admin_ids[0])
    assert reader.update_assignment(replace(original, start_date='2026-01-02', notes=' trimmed '))
    row = reader.get_assignments(task_id=11)[0]
    assert row['effective_start_date'] == '2026-01-02' and row['effective_end_date'] == '2026-01-05'
    assert row['notes'] == 'trimmed'
    assert authorized.query('SELECT start_date FROM eppm.resource_pool_assignment WHERE id=%s', (admin_ids[0],)) == [(date(2026, 1, 2),)]
    task_map = reader.get_task_assignments_map([11, 12, 13, 999])
    assert set(task_map) == {11, 12} and task_map[11][0]['start_date'] == '2026-01-02'
    project_map = reader.get_project_assignments_map([1, 2, 3, 999])
    assert set(project_map) == {1, 2} and project_map[1][0]['id'] == direct[0]
    assert reader.get_project_assignments_map([]) == reader.get_task_assignments_map([]) == {}
    assert reader.get_assignment_by_id(admin_ids[2]) is None
    assert gateway(authorized, 1).run(lambda store: store.get_assignments(pool_ids=[])) == []
    assert len(gateway(authorized, 1).run(lambda store: store.get_assignments(pool_ids=[pool]))) == 4
    assert reader.delete_assignment(admin_ids[0]) and reader.get_assignment_by_id(admin_ids[0]) is None
    assert not reader.delete_assignment(999) and not reader.update_assignment(PoolAssignment(pool, 1, 1))
    assert not reader.update_assignment(PoolAssignment(pool, 1, 1, id=999))
    with pytest.raises(ValueError):
        reader.create_assignment(PoolAssignment(pool, 1, 1, start_date='2026-02-30'))
    with pytest.raises(AccessDenied):
        reader.create_assignment(PoolAssignment(pool, 1, 1, task_id=12))
    with pytest.raises(AccessDenied):
        pools.create_assignment(PoolAssignment(pool, 1, 1, task_id=12))


def test_shared_configuration_and_old_new_assignment_owners_are_authoritative(pools, authorized):
    pool = pools.create_pool(ResourcePool('Pool'))
    owned = pools.create_assignment(PoolAssignment(pool, 1, 1))
    read_only = pools.create_assignment(PoolAssignment(pool, 2, 1))
    hidden = pools.create_assignment(PoolAssignment(pool, 3, 1))
    reader = service(authorized, 1)
    for operation in (lambda: reader.get_all_pools(), lambda: reader.get_all_mappings(), lambda: reader.get_tag_choices(),
                      lambda: reader.create_pool(ResourcePool('Denied')), lambda: reader.delete_pool(pool),
                      lambda: reader.create_mapping(PoolMapping(pool, 'team', 1)),
                      lambda: reader.create_assignment(PoolAssignment(pool, 2, 1)),
                      lambda: reader.update_assignment(PoolAssignment(pool, 2, 1, id=owned)),
                      lambda: reader.update_assignment(PoolAssignment(pool, 1, 1, id=read_only)),
                      lambda: reader.delete_assignment(read_only)):
        with pytest.raises(AccessDenied):
            operation()
    assert not reader.delete_assignment(hidden)
    assert not reader.update_assignment(PoolAssignment(pool, 1, 1, id=hidden))
    assert reader.get_assignment_by_id(owned).project_id == 1
    assert pools.get_assignment_by_id(read_only).project_id == 2
    with pytest.raises(AccessDenied):
        service(authorized, 3).pool_choices()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query("INSERT INTO eppm.resource_pool(name) VALUES ('Direct denied')", write=True)


def test_late_tag_insert_failure_restores_pool_details_and_existing_links(pools, authorized):
    pool = pools.create_pool(ResourcePool('Original'), tag_ids=[1])
    original, tags = pools.get_pool_by_id(pool), pools.get_pool_tags(pool)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_pool_tag() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Test constraint' USING ERRCODE='23514'; END $$""")
        connection.execute('CREATE TRIGGER reject_pool_tag BEFORE INSERT ON eppm.resource_pool_tag FOR EACH ROW EXECUTE FUNCTION eppm.reject_pool_tag()')
    with pytest.raises(ResourcePoolConflictError):
        pools.update_pool(replace(original, name='Lost'), tag_ids=[2])
    assert pools.get_pool_by_id(pool) == original and pools.get_pool_tags(pool) == tags


def test_pool_soft_delete_is_atomic_and_preserves_assignments_tags_and_mappings(pools, authorized):
    pool = pools.create_pool(ResourcePool('Pool'), tag_ids=[1])
    group = create_container(pools, ResourcePool('Group'), pool_ids=[pool])
    mapping = pools.create_mapping(PoolMapping(pool, 'team', 1))
    assignment = pools.create_assignment(PoolAssignment(pool, 3, 1))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_pool_delete() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Test constraint' USING ERRCODE='23514'; END $$""")
        connection.execute('CREATE TRIGGER reject_pool_delete AFTER UPDATE OF deleted_flag ON eppm.resource_pool FOR EACH ROW EXECUTE FUNCTION eppm.reject_pool_delete()')
    with pytest.raises(ResourcePoolConflictError):
        pools.delete_pool(pool)
    assert pools.get_assignment_by_id(assignment) and pools.get_mappings_by_pool(pool)[0].id == mapping
    assert pools.get_pool_tags(pool)[0].tag_id == 1 and pools.get_pool_by_id(pool).parent_pool_id == group
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('DROP TRIGGER reject_pool_delete ON eppm.resource_pool')
    assert pools.delete_pool(pool)
    assert pools.get_assignments() == [] and pools.get_all_mappings() == [] and pools.get_pool_tags(pool) == []
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT deleted_flag FROM eppm.resource_pool WHERE id=%s', (pool,)).fetchone() == (True,)
        assert connection.execute('SELECT id FROM eppm.resource_pool_mapping WHERE pool_id=%s', (pool,)).fetchone() == (mapping,)
        assert connection.execute('SELECT id FROM eppm.resource_pool_assignment WHERE pool_id=%s', (pool,)).fetchone() == (assignment,)
        assert connection.execute('SELECT tag_id FROM eppm.resource_pool_tag WHERE pool_id=%s', (pool,)).fetchone() == (1,)
    assert pools.descendant_pool_ids(group) == [group]


class GatedGateway(PostgresResourcePoolGateway):
    def __init__(self, authorized, barrier, attempts, index):
        super().__init__(authorized.database, authorized.key, access=authorized.binding(4).access)
        self.barrier, self.attempts, self.index = barrier, attempts, index

    def run(self, operation, **options):
        def callback(store):
            self.attempts[self.index] += 1
            if self.attempts[self.index] == 1:
                self.barrier.wait(timeout=10)
            return operation(store)
        return super().run(callback, **options)


def test_competing_recursive_edges_replay_and_revalidate_without_committing_a_cycle(pools, authorized):
    groups = [create_container(pools, ResourcePool(name)) for name in ('One', 'Two')]
    barrier, attempts = Barrier(2), [0, 0]
    def connect(index):
        actor_service = ResourcePoolService(GatedGateway(authorized, barrier, attempts, index))
        try:
            actor_service.update_pool(ResourcePool(('One', 'Two')[index], id=groups[index], parent_pool_id=groups[1 - index]))
            return 'saved'
        except ValueError as error:
            assert 'circular' in str(error)
            return 'cycle'
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(connect, range(2)))
    assert sorted(outcomes) == ['cycle', 'saved'] and sum(attempts) >= 3
    assert len(pools.group_membership()) == 1


def test_concurrent_mapping_upsert_replays_to_one_identity(pools, authorized):
    pool = pools.create_pool(ResourcePool('Pool'))
    barrier, attempts = Barrier(2), [0, 0]
    def upsert(index):
        return ResourcePoolService(GatedGateway(authorized, barrier, attempts, index)).create_mapping(PoolMapping(pool, 'team', 1, 25 + index))
    with ThreadPoolExecutor(max_workers=2) as executor:
        identities = list(executor.map(upsert, range(2)))
    assert identities[0] == identities[1] and sum(attempts) >= 3
    assert len(pools.get_all_mappings()) == 1


def test_concurrent_pool_name_and_tags_remain_one_committed_pair(pools, authorized):
    pool = pools.create_pool(ResourcePool('Original'))
    barrier, attempts = Barrier(2), [0, 0]
    def save(index):
        return ResourcePoolService(GatedGateway(authorized, barrier, attempts, index)).update_pool(
            ResourcePool(f'Name {index + 1}', id=pool), tag_ids=[index + 1])
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert all(executor.map(save, range(2)))
    assert sum(attempts) >= 3
    assert pools.get_pool_by_id(pool).name == f'Name {pools.get_pool_tags(pool)[0].tag_id}'


def test_pool_catalog_and_parent_links_share_a_repeatable_read_snapshot(pools, authorized):
    parent = pools.create_pool(ResourcePool('Original'))
    leaf = pools.create_pool(ResourcePool('Leaf', parent_pool_id=parent))
    ready, changed = Event(), Event()
    def read():
        def operation(store):
            before = store.get_all_pools()
            ready.set()
            assert changed.wait(timeout=10)
            return before, store.get_all_pools()
        return gateway(authorized).run(operation)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(read)
        assert ready.wait(timeout=10)
        try:
            pools.update_pool(replace(pools.get_pool_by_id(leaf), parent_pool_id=None))
        finally:
            changed.set()
        before, after = future.result()
    assert before == after
    assert next(row for row in before if row.id == leaf).parent_pool_id == parent
    assert pools.get_pool_by_id(leaf).parent_pool_id is None


@pytest.mark.parametrize('kind', ['pool', 'child', 'assignment'])
def test_retry_retains_original_model_and_collection_inputs(pools, authorized, kind):
    pool = pools.create_pool(ResourcePool('Original'))
    submitted_tags, submitted_pools = [1], [pool]
    models = {'pool': ResourcePool('Kept', id=pool), 'child': ResourcePool('Kept', parent_pool_id=pool), 'assignment': PoolAssignment(pool, 1, 0.75)}
    model, attempts = models[kind], []
    table, action = {'pool': ('resource_pool_tag', 'INSERT'), 'child': ('resource_pool', 'INSERT'),
                     'assignment': ('resource_pool_assignment', 'INSERT')}[kind]
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('CREATE SEQUENCE eppm.pool_attempt')
        connection.execute('GRANT USAGE ON SEQUENCE eppm.pool_attempt TO eppm_runtime')
        connection.execute("""CREATE FUNCTION eppm.retry_pool_once() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF nextval('eppm.pool_attempt')=1 THEN RAISE EXCEPTION 'Known rollback' USING ERRCODE='40001'; END IF;
            RETURN NEW; END $$""")
        connection.execute(f'CREATE TRIGGER retry_pool_once BEFORE {action} ON eppm.{table} FOR EACH ROW EXECUTE FUNCTION eppm.retry_pool_once()')
    class ChangedInputGateway(PostgresResourcePoolGateway):
        def run(self, operation, **options):
            def callback(store):
                attempts.append(1)
                if len(attempts) == 2:
                    submitted_tags[0] = 999
                    submitted_pools[0] = 999
                    if kind == 'assignment':
                        model.fte_assigned = 99
                    else:
                        model.name = 'Changed outside callback'
                return operation(store)
            return super().run(callback, **options)
    actor_service = ResourcePoolService(ChangedInputGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    if kind == 'pool':
        actor_service.update_pool(model, tag_ids=submitted_tags)
        assert pools.get_pool_by_id(pool).name == 'Kept' and pools.get_pool_tags(pool)[0].tag_id == 1
    elif kind == 'child':
        child = actor_service.create_pool(model)
        assert pools.get_pool_by_id(child).name == 'Kept' and pools.get_pool_by_id(child).parent_pool_id == pool
    else:
        identity = actor_service.create_assignment(model)
        assert pools.get_assignment_by_id(identity).fte_assigned == 0.75
    assert len(attempts) == 2


def test_native_dates_and_creation_timestamps_ignore_session_locale(pools, authorized):
    pool = pools.create_pool(ResourcePool('Pool'))
    original = pools.get_pool_by_id(pool)
    assignment = pools.create_assignment(PoolAssignment(pool, 1, 1, start_date='2026-03-04', end_date='2026-04-05'))
    def operation(store):
        store.connection.execute("SET LOCAL DateStyle='SQL, DMY'")
        store.connection.execute("SET LOCAL TIME ZONE 'Pacific/Auckland'")
        return store.get_pool_by_id(pool), store.get_assignment_by_id(assignment)
    loaded_pool, loaded_assignment = gateway(authorized).run(operation)
    assert loaded_pool.created_at == original.created_at
    assert (loaded_assignment.start_date, loaded_assignment.end_date) == ('2026-03-04', '2026-04-05')


def test_nullable_legacy_descriptions_and_notes_remain_editable(pools, authorized):
    pool = pools.create_pool(ResourcePool('Pool'))
    group = create_container(pools, ResourcePool('Group'))
    assignment = pools.create_assignment(PoolAssignment(pool, 1, 1))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.resource_pool SET description=NULL,created_at=NULL')
        connection.execute('UPDATE eppm.resource_pool_assignment SET notes=NULL')
    assert pools.get_pool_by_id(pool).description == pools.get_pool_by_id(group).description == ''
    assert pools.get_pool_by_id(pool).created_at is None and pools.get_pool_by_id(group).created_at is None
    assert pools.get_assignment_by_id(assignment).notes == ''
    assert pools.update_pool(pools.get_pool_by_id(pool))
    assert pools.update_pool(pools.get_pool_by_id(group))
    assert pools.update_assignment(pools.get_assignment_by_id(assignment))


def test_pool_outages_leave_safe_errors_and_logs(pools, authorized, caplog):
    authorized.database.close()
    with pytest.raises(ResourcePoolStorageError) as error:
        pools.get_all_pools()
    assert 'postgresql://' not in str(error.value) + caplog.text
