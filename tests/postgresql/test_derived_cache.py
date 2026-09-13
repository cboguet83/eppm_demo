"""Native cache publication, source invalidation and current authorization."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, timedelta
from hashlib import sha256
import json
from threading import Barrier

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from app.application.exceptions import PlanningStorageError, ResourcePoolStorageError
from app.application.services.business_access import BusinessAccess
from app.application.services.planning import PlanningService
from app.application.services.pool_capacity import PoolCapacityService
from app.domain.access.models import AccessDenied, Actor
from app.domain.resources.models import PoolCapacitySummary
from app.infrastructure.postgresql.authorization import ServerRequestSigner
from app.infrastructure.postgresql.capacity_cache import PostgresCapacityCache
from app.infrastructure.postgresql.derived_cache import CacheRecord, DerivedCacheState, PostgresDerivedCache
from app.infrastructure.postgresql.planning import PostgresPlanningGateway
from app.infrastructure.postgresql.pool_capacity import PostgresCapacityReader
from app.infrastructure.postgresql.revisions import snapshot
from tests.postgresql.test_pool_capacity import staffing


DAY = date(2026, 1, 3)


def cache(authorized, user_id=1, state=None, access=None):
    return PostgresDerivedCache(authorized.database, authorized.key, state or DerivedCacheState(),
                               access=access or authorized.binding(user_id).access)


def capacity(authorized, user_id=1, state=None, today=lambda: DAY):
    access = authorized.binding(user_id).access
    adapter = PostgresCapacityCache(authorized.database, authorized.key, state or DerivedCacheState(), today, access=access)
    reader = PostgresCapacityReader(authorized.database, authorized.key, access=access)
    return PoolCapacityService(reader, adapter, today)


def body_for(derived, kind='planning', identities=(1,)):
    rows = derived.read(kind, list(identities), DAY, False, [])
    identity_field = 'pool_id' if kind == 'capacity' else 'id'
    return json.dumps({'kind': kind, 'day': DAY.isoformat(), 'version': 1, 'entries': [
        {'entity_id': identity, 'token': token, 'summary': {identity_field: identity},
         'detail': {identity_field: identity, 'assignments': [], 'contributing_resources': []}}
        for identity, token, *_ in rows
    ]})


def publish_raw(authorized, body, *, user_id=1, proof=None, purpose='cache.publish', write=True):
    def operation(connection):
        document, signature = proof or ServerRequestSigner(authorized.key).sign(
            connection, purpose, {'body_hash': sha256(body.encode()).hexdigest()})
        return connection.execute('SELECT eppm.publish_derived_cache(%s,%s,%s)', (document, signature, body)).fetchone()[0]
    return authorized.database.run(operation, write=write, bind=authorized.binding(user_id))


def test_sql_cache_keys_match_python_revisions_and_filter_requested_visible_entities(staffing):
    staffing.query("INSERT INTO eppm.project(id,name) VALUES (4,'Whole-project source')", user_id=4, write=True)
    staffing.query('INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES (1,2),(2,1)', user_id=4, write=True)
    staffing.query('INSERT INTO eppm.task_dependencies(task_id,predecessor_project_id) VALUES (1,4)', user_id=4, write=True)
    staffing.query('UPDATE eppm.project_task SET predecessor_id=3 WHERE id=1', user_id=4, write=True)
    for user_id in (1, 2, 4):
        derived = cache(staffing, user_id)
        revisions = snapshot(staffing.database, staffing.key, staffing.binding(user_id).access)
        selected = [1, 2, 3, 4, 999]
        rows = staffing.query('SELECT * FROM eppm.planning_task_source_keys(%s::bigint[])', (selected,), user_id=user_id)
        pairs = set(staffing.query('SELECT DISTINCT project_id,pool_id FROM eppm.resource_pool_assignment WHERE task_id IS NOT NULL', user_id=user_id))
        assert dict(rows) == revisions.task_tokens(selected, pairs)
        for kind, expected in (('capacity', revisions.pool_tokens()), ('planning', revisions.project_tokens())):
            rows = derived.read(kind, None, DAY, False, [])
            assert {row[0]: row[1] for row in rows} == expected
            assert not any(row[3] for row in rows)
            assert derived.read(kind, [], DAY, False, []) == []
            subset = derived.read(kind, [1, 3, 999, 1], DAY, False, [])
            assert {row[0] for row in subset} == set(expected) & {1, 3}


def test_capacity_cold_database_and_memory_hits_preserve_details_and_caller_independence(staffing):
    state = DerivedCacheState()
    service = capacity(staffing, 4, state)
    expected = service.calculate_many([1, 2, 3], DAY)
    before = snapshot(staffing.database, staffing.key, staffing.binding(4).access)
    assert service.get_details([1, 2, 3]) == sorted(expected, key=lambda row: row.pool_name)
    assert snapshot(staffing.database, staffing.key, staffing.binding(4).access) == before
    # A fresh process must obtain persisted data without calculating again.
    fresh = capacity(staffing, 4)
    fresh.calculate_many = lambda *_: pytest.fail('A current persisted entry must be reused')
    assert fresh.get_details([1, 2, 3]) == sorted(expected, key=lambda row: row.pool_name)
    service.calculate_many = lambda *_: pytest.fail('A current memory entry must be reused')
    summaries = service.get_summaries([1])
    assert summaries == [PoolCapacitySummary(**{key: asdict(expected[0])[key] for key in PoolCapacitySummary.__dataclass_fields__})]
    first = service.get_details([1])[0]
    first.assignments.clear()
    first.contributing_resources[0].function_name = 'Caller mutation'
    assert service.get_details([1]) == [expected[0]]
    assert all(entry.complete for entry in state.entries.values())


def test_summary_database_hit_does_not_prevent_later_detail_fetch(staffing):
    capacity(staffing).get_summaries([1])
    state = DerivedCacheState()
    service = capacity(staffing, state=state)
    service.calculate_many = lambda *_: pytest.fail('A current persisted entry must be reused')
    assert service.get_summaries([1])[0].pool_name == 'Staffed'
    assert not next(iter(state.entries.values())).complete
    assert service.get_details([1])[0].assignments
    assert next(iter(state.entries.values())).complete
    assert service.get_summaries([999]) == []


def test_memory_isolated_by_actor_session_and_current_staff_permission(staffing):
    state = DerivedCacheState()
    admin = capacity(staffing, 4, state).get_details([1])[0]
    reader = capacity(staffing, 1, state).get_details([1])[0]
    other = capacity(staffing, 2, state).get_details([1])[0]
    assert admin.contributing_resources and reader.contributing_resources == other.contributing_resources == []
    assert {row['project_id'] for row in reader.assignments} == {1, 2}
    assert {row['project_id'] for row in other.assignments} == {3}
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.app_session VALUES ('second-session',1,950,2000,980,false,false)")
    access = BusinessAccess(Actor(1, 'second-session', 'request'), staffing.binding(1).access.policy)
    derived = cache(staffing, state=state, access=access)
    rows = derived.read('capacity', [1], DAY, True, list(state.snapshot('capacity', DAY, True)))
    assert not rows[0][3]
    with pytest.raises(AccessDenied):
        capacity(staffing, 3, state).get_summaries()


@pytest.mark.parametrize('change', ['grant', 'revoke', 'logout', 'expiry'])
def test_warm_memory_is_reauthorized_after_permission_or_session_changes(staffing, change):
    state = DerivedCacheState()
    service = capacity(staffing, state=state)
    service.get_details([1])
    if change == 'grant':
        staffing.query("SELECT eppm.admin_grant(1,'project_viewer',%s)",
                       (Jsonb({'kind': 'projects', 'project_ids': [3]}),), user_id=5, write=True)
        assert {row['project_id'] for row in service.get_details([1])[0].assignments} == {1, 2, 3}
    elif change == 'revoke':
        with psycopg.connect(staffing.setup.operator_url) as connection:
            grants = connection.execute('SELECT id FROM eppm.app_role_assignment WHERE user_id=1').fetchall()
        for grant, in grants:
            staffing.query('SELECT eppm.admin_revoke(%s)', (grant,), user_id=5, write=True)
        with pytest.raises(AccessDenied):
            service.get_details([1])
    else:
        with psycopg.connect(staffing.setup.operator_url) as connection:
            connection.execute('UPDATE eppm.app_session SET ' + ('revoked=true' if change == 'logout' else 'expires_at=999') + " WHERE session_hash='session-1'")
        with pytest.raises(AccessDenied):
            service.get_details([1])


def test_source_change_during_calculation_rejects_publication_and_recalculates(staffing):
    service = capacity(staffing)
    original = service.calculate_many
    calls = []
    def calculate(selected, day):
        calls.append(list(selected))
        results = original(selected, day)
        if len(calls) == 1:
            staffing.query('UPDATE eppm.resource_pool_assignment SET fte_assigned=3 WHERE pool_id=1 AND project_id=1', write=True)
        return results
    service.calculate_many = calculate
    result = service.get_details([1])
    assert result == original([1], DAY) and calls == [[1], [1]]


def test_hidden_and_unrelated_sources_reuse_entry_but_current_key_never_accepts_stale_tokens(staffing):
    service = capacity(staffing)
    service.get_summaries([2])
    derived = cache(staffing)
    before = derived.read('capacity', [2], DAY, False, [])[0]
    staffing.query('UPDATE eppm.resource_pool_assignment SET fte_assigned=100 WHERE project_id=3', user_id=4, write=True)
    staffing.query('UPDATE eppm.resource_pool SET capacity_fte=100 WHERE id=6', user_id=4, write=True)
    assert derived.read('capacity', [2], DAY, False, [])[0] == before
    staffing.query('UPDATE eppm.project_task SET progress_pct=50 WHERE id=1', write=True)
    after = derived.read('capacity', [2], DAY, False, [before[1]])[0]
    assert after[1] != before[1] and after[2] is None and not after[3]
    assert service.get_summaries([2])


def test_current_day_and_format_are_required_and_storage_has_one_row_per_session_entity(staffing):
    day = [DAY]
    service = capacity(staffing, today=lambda: day[0])
    service.get_details([1])
    assert not cache(staffing).read('capacity', [1], DAY + timedelta(days=1), True, [])[0][3]
    day[0] += timedelta(days=1)
    service.get_details([1])
    with psycopg.connect(staffing.setup.operator_url) as connection:
        assert connection.execute('SELECT day,count(*) FROM eppm.pool_capacity_cache GROUP BY day').fetchall() == [(day[0], 1)]
        connection.execute('UPDATE eppm.pool_capacity_cache SET format_version=2')
    assert not cache(staffing).read('capacity', [1], day[0], False, [])[0][3]


def test_calculations_for_independent_requests_never_hold_a_process_lock(staffing):
    state, barrier = DerivedCacheState(), Barrier(2)
    def request(identity):
        service = capacity(staffing, state=state)
        original = service.calculate_many
        def calculate(selected, day):
            barrier.wait(timeout=10)
            return original(selected, day)
        service.calculate_many = calculate
        return service.get_details([identity])
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(request, identity) for identity in (1, 2)]
        assert all(future.result(timeout=20) for future in futures)


def test_planning_headers_use_read_only_snapshots_and_independent_publication(staffing):
    class ObservedGateway(PostgresPlanningGateway):
        def run(self, operation, **options):
            def inspect(store):
                assert store.connection.execute("SELECT current_setting('transaction_read_only'),current_setting('transaction_isolation')").fetchone() == ('on', 'repeatable read')
                return operation(store)
            return super().run(inspect, **options)
    gateway = ObservedGateway(staffing.database, staffing.key, access=staffing.binding(1).access)
    service = PlanningService(gateway)
    staffing.query('INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES (1,3)', user_id=4, write=True)
    headers = service.get_project_summaries([3, 2, 1, 1])
    assert [row['id'] for row in headers] == [1, 2] and not headers[0]['hasViolations']
    service.get_project_summaries([])
    assert service.get_project_summaries([1, 2]) == headers
    staffing.query('INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES (1,2)', user_id=4, write=True)
    assert service.get_project_summaries([1])[0]['hasViolations']
    staffing.query("UPDATE eppm.project_task SET end_date='2025-12-31',start_date='2025-12-30' WHERE id=2", user_id=4, write=True)
    assert not service.get_project_summaries([1])[0]['hasViolations']


def test_private_tables_and_key_function_cannot_be_accessed_by_runtime(staffing):
    for table in ('pool_capacity_cache', 'planning_summary_cache'):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            staffing.query(sql.SQL('SELECT * FROM eppm.{}').format(sql.Identifier(table)), user_id=4)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            staffing.query(sql.SQL('DELETE FROM eppm.{}').format(sql.Identifier(table)), user_id=4, write=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        staffing.query("SELECT * FROM eppm.current_cache_keys('planning',NULL)", user_id=4)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        staffing.database.run(lambda connection: connection.execute("SELECT * FROM eppm.read_derived_cache('planning',NULL,CURRENT_DATE,1,false,'{}')").fetchall())


def test_publication_requires_a_valid_transaction_bound_server_proof(staffing):
    body = body_for(cache(staffing))
    for proof, purpose in ((('{}', 'invalid'), 'cache.publish'), (None, 'wrong.purpose')):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            publish_raw(staffing, body, proof=proof, purpose=purpose)
    old_proof = staffing.database.run(lambda connection: ServerRequestSigner(staffing.key).sign(
        connection, 'cache.publish', {'body_hash': sha256(body.encode()).hexdigest()}), write=True, bind=staffing.binding())
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        publish_raw(staffing, body, proof=old_proof)
    with pytest.raises(psycopg.errors.ActiveSqlTransaction):
        publish_raw(staffing, body, write=False)
    assert publish_raw(staffing, body)


def test_publication_rejects_hidden_projects_and_hidden_assignment_payloads(staffing):
    hidden = body_for(cache(staffing, 4), identities=(3,))
    assert not publish_raw(staffing, hidden)
    body = json.loads(body_for(cache(staffing), 'capacity'))
    body['entries'][0]['detail']['assignments'] = [{'project_id': 3}]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        publish_raw(staffing, json.dumps(body))
    body['entries'][0]['detail']['assignments'] = []
    body['entries'][0]['detail']['contributing_resources'] = [{'employee_name': 'Never exposed'}]
    assert publish_raw(staffing, json.dumps(body))
    result = cache(staffing).read('capacity', [1], DAY, True, [])[0][2]
    assert result['contributing_resources'] == []


def test_memory_limits_bound_serialized_bytes_and_keep_complete_records():
    with pytest.raises(ValueError):
        DerivedCacheState(max_entries=0)
    state = DerivedCacheState(max_entries=2, max_bytes=25)
    state.remember('planning', DAY, 'one', {'v': 1}, complete=True)
    state.remember('planning', DAY, 'one', {'v': 2}, complete=False)
    assert json.loads(state.snapshot('planning', DAY, True)['one'].raw) == {'v': 1}
    state.remember('planning', DAY, 'two', {'v': 2}, complete=False)
    assert 'two' not in state.snapshot('planning', DAY, True)
    state.remember('planning', DAY, 'three', {'v': 3}, complete=True)
    assert 'one' not in state.snapshot('planning', DAY, False)
    state.remember('planning', DAY, 'three', {'v': 'longer'}, complete=True)
    assert state.size_bytes == sum(len(entry.raw) for entry in state.entries.values()) <= 25
    state.remember('planning', DAY, 'oversized', {'v': 'x' * 26}, complete=True)
    assert len(state.entries) == 2
    state.remember('planning', DAY, 'four', {'v': 'x' * 15}, complete=True)
    assert len(state.entries) == 1 and state.size_bytes <= 25


def test_confirmed_memory_hits_refresh_eviction_order_without_resurrecting_evicted_entries():
    state = DerivedCacheState(max_entries=2)
    for token in ('one', 'two'):
        state.remember('planning', DAY, token, {'id': 1}, complete=True)
    state.touch('planning', DAY, 'one')
    state.remember('planning', DAY, 'three', {'id': 3}, complete=True)
    state.touch('planning', DAY, 'two')
    assert list(state.snapshot('planning', DAY, True)) == ['one', 'three']


def test_signed_body_hash_cannot_be_reused_for_a_modified_body(staffing):
    body = body_for(cache(staffing))
    def operation(connection):
        document, signature = ServerRequestSigner(staffing.key).sign(
            connection, 'cache.publish', {'body_hash': sha256(body.encode()).hexdigest()})
        return connection.execute('SELECT eppm.publish_derived_cache(%s,%s,%s)', (document, signature, body + ' ')).fetchone()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        staffing.database.run(operation, write=True, bind=staffing.binding())


def test_serialization_retry_signs_a_new_proof_and_replays_complete_publication(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('CREATE SEQUENCE eppm.cache_attempt')
        connection.execute("""CREATE FUNCTION eppm.retry_cache_once() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF nextval('eppm.cache_attempt')=1 THEN RAISE EXCEPTION 'Known rollback' USING ERRCODE='40001'; END IF;
            RETURN NEW; END $$""")
        connection.execute('CREATE TRIGGER retry_cache_once BEFORE INSERT ON eppm.pool_capacity_cache '
                           'FOR EACH ROW EXECUTE FUNCTION eppm.retry_cache_once()')
    service = capacity(staffing)
    assert service.get_details([1]) == service.calculate_many([1], DAY)
    with psycopg.connect(staffing.setup.operator_url) as connection:
        assert connection.execute('SELECT last_value FROM eppm.cache_attempt').fetchone()[0] == 2
        assert connection.execute('SELECT count(*) FROM eppm.pool_capacity_cache').fetchone()[0] == 1


def test_late_cache_insert_failure_rolls_back_the_entire_publication(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_second_cache() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.pool_id=2 THEN RAISE EXCEPTION 'Rejected derived row' USING ERRCODE='23514'; END IF;
            RETURN NEW; END $$""")
        connection.execute('CREATE TRIGGER reject_second_cache BEFORE INSERT ON eppm.pool_capacity_cache '
                           'FOR EACH ROW EXECUTE FUNCTION eppm.reject_second_cache()')
    before = snapshot(staffing.database, staffing.key, staffing.binding().access)
    with pytest.raises(ResourcePoolStorageError, match='could not be accessed'):
        capacity(staffing).get_details([1, 2])
    assert snapshot(staffing.database, staffing.key, staffing.binding().access) == before
    with psycopg.connect(staffing.setup.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.pool_capacity_cache').fetchone()[0] == 0


def test_security_change_during_calculation_discards_payload_and_recalculates_scope(staffing):
    service = capacity(staffing)
    original, calls = service.calculate_many, []
    def calculate(selected, day):
        calls.append(1)
        result = original(selected, day)
        if len(calls) == 1:
            staffing.query("SELECT eppm.admin_grant(1,'project_viewer',%s)",
                           (Jsonb({'kind': 'projects', 'project_ids': [3]}),), user_id=5, write=True)
        return result
    service.calculate_many = calculate
    assert {row['project_id'] for row in service.get_details([1])[0].assignments} == {1, 2, 3}
    assert len(calls) == 2


def test_permission_change_with_unchanged_read_scope_invalidates_persisted_and_memory_keys(staffing):
    state = DerivedCacheState()
    capacity(staffing, state=state).get_details([1])
    before = snapshot(staffing.database, staffing.key, staffing.binding().access)
    staffing.query("SELECT eppm.admin_grant(1,'project_editor',%s)",
                   (Jsonb({'kind': 'projects', 'project_ids': [2]}),), user_id=5, write=True)
    after = snapshot(staffing.database, staffing.key, staffing.binding().access)
    assert after.scope == before.scope
    row = cache(staffing).read('capacity', [1], DAY, True, list(state.snapshot('capacity', DAY, True)))[0]
    assert row[1] != before.pool_tokens()[1] and not row[3]


def test_repeated_source_changes_return_safe_failure_without_publishing(staffing):
    service = capacity(staffing)
    original, calls = service.calculate_many, []
    def calculate(selected, day):
        calls.append(1)
        result = original(selected, day)
        staffing.query('UPDATE eppm.project_task SET progress_pct=progress_pct+1 WHERE id=1', write=True)
        return result
    service.calculate_many = calculate
    with pytest.raises(ResourcePoolStorageError, match='changed repeatedly'):
        service.get_details([1])
    assert len(calls) == 3
    assert not cache(staffing).read('capacity', [1], DAY, True, [])[0][3]


def test_outage_and_missing_metadata_fail_before_reusing_memory_or_calculating(staffing, caplog):
    state = DerivedCacheState()
    service = capacity(staffing, state=state)
    service.get_details([1])
    service.calculate_many = lambda *_: pytest.fail('Unverifiable sources cannot be calculated')
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.catalog_cache_revision')
    with pytest.raises(ResourcePoolStorageError, match='could not be accessed'):
        service.get_details([1])
    staffing.database.close()
    with pytest.raises(PlanningStorageError, match='could not be accessed'):
        cache(staffing).load('planning', [1], DAY, lambda _: pytest.fail('No database'))
    assert 'postgresql://' not in caplog.text


@pytest.mark.parametrize('payload', ['missing', 'nonfinite', 'incomplete', 'detail_shape'])
def test_invalid_calculation_or_cached_payload_returns_safe_application_error(staffing, payload):
    derived = cache(staffing)
    if payload == 'incomplete':
        with pytest.raises(PlanningStorageError, match='incomplete data'):
            derived.load('planning', [1], DAY, lambda _: [])
    elif payload == 'nonfinite':
        with pytest.raises(PlanningStorageError, match='could not be decoded'):
            derived.load('planning', [1], DAY, lambda _: [CacheRecord(1, {'id': 1, 'n': float('nan')}, {'id': 1})])
    else:
        service = capacity(staffing)
        service.get_details([1])
        with psycopg.connect(staffing.setup.operator_url) as connection:
            connection.execute('UPDATE eppm.pool_capacity_cache SET ' +
                               ("summary='{}'" if payload == 'missing' else "detail='{}'"))
        with pytest.raises(ResourcePoolStorageError, match='could not be decoded'):
            if payload == 'missing':
                capacity(staffing).get_summaries([1])
            else:
                capacity(staffing).get_details([1])


@pytest.mark.parametrize('invalid', ['kind', 'version', 'entries', 'duplicate', 'identity', 'token'])
def test_invalid_publication_is_rejected_atomically(staffing, invalid):
    body = json.loads(body_for(cache(staffing)))
    if invalid == 'kind':
        body['kind'] = 'unknown'
    elif invalid == 'version':
        body['version'] = 0
    elif invalid == 'entries':
        body['entries'] = {}
    elif invalid == 'duplicate':
        body['entries'] *= 2
    elif invalid == 'identity':
        body['entries'][0]['summary']['id'] = 2
    else:
        body['entries'][0]['token'] = 'invalid'
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        publish_raw(staffing, json.dumps(body))
    assert not cache(staffing).read('planning', [1], DAY, False, [])[0][3]


@pytest.mark.parametrize('owner', ['project', 'pool', 'session'])
def test_deleting_cache_owner_removes_private_entries_by_foreign_key(authorized, owner):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name) VALUES (1,'Temporary')")
    derived = cache(authorized)
    assert publish_raw(authorized, body_for(derived))
    assert publish_raw(authorized, body_for(derived, 'capacity'))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        if owner == 'project':
            connection.execute('DELETE FROM eppm.project WHERE id=1')
        elif owner == 'pool':
            connection.execute('DELETE FROM eppm.resource_pool WHERE id=1')
        else:
            connection.execute("DELETE FROM eppm.app_session WHERE session_hash='session-1'")
        assert connection.execute('SELECT count(*) FROM eppm.planning_summary_cache').fetchone()[0] == (1 if owner == 'pool' else 0)
        assert connection.execute('SELECT count(*) FROM eppm.pool_capacity_cache').fetchone()[0] == (1 if owner == 'project' else 0)


def test_memory_uses_frozen_publication_payload_even_if_calculator_mutates_its_records(authorized):
    payload = {'id': 1, 'name': 'Original'}
    class MutatingCache(PostgresDerivedCache):
        def publish(self, kind, body):
            accepted = super().publish(kind, body)
            payload['name'] = 'Changed after publication'
            return accepted
    derived = MutatingCache(authorized.database, authorized.key, DerivedCacheState(), access=authorized.binding().access)
    assert derived.load('planning', [1], DAY, lambda _: [CacheRecord(1, payload, payload)]) == [{'id': 1, 'name': 'Original'}]
    assert cache(authorized).read('planning', [1], DAY, False, [])[0][2] == {'id': 1, 'name': 'Original'}


def test_large_details_use_a_small_hash_proof_without_limiting_the_existing_projection(authorized):
    payload = {'id': 1, 'name': 'A' * (1024 * 1024 + 100)}
    derived = cache(authorized)
    assert derived.load('planning', [1], DAY, lambda _: [CacheRecord(1, payload, payload)]) == [payload]
    assert cache(authorized).read('planning', [1], DAY, False, [])[0][2] == payload


def test_current_staff_permission_redacts_full_payloads_on_database_and_memory_hits(staffing):
    state = DerivedCacheState()
    service = capacity(staffing, state=state)
    service.get_details([1])
    full = asdict(capacity(staffing, 4).calculate_many([1], DAY)[0])
    full['assignments'] = [row for row in full['assignments'] if row['project_id'] in (1, 2)]
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.pool_capacity_cache SET detail=%s WHERE user_id=1', (Jsonb(full),))
    assert capacity(staffing).get_details([1])[0].contributing_resources == []
    token = cache(staffing).read('capacity', [1], DAY, True, [])[0][1]
    state.remember('capacity', DAY, token, full, complete=True)
    assert service.get_details([1])[0].contributing_resources == []


def test_empty_publication_still_requires_business_read_access(authorized):
    body = json.dumps({'kind': 'planning', 'day': DAY.isoformat(), 'version': 1, 'entries': []})
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        publish_raw(authorized, body, user_id=3)
    assert publish_raw(authorized, body)
