"""Capacity caching discards results when persisted access or inputs change mid-read."""

from tests.postgresql.plan_fixtures import seed_test_plans
import json
from datetime import date

import psycopg
from psycopg import sql as pg_sql
import pytest

from app.application.exceptions import ResourcePoolStorageError
from app.infrastructure.postgresql.derived_cache import DerivedCacheState
from app.infrastructure.postgresql.capacity_cache import PostgresCapacityCache
from app.main import create_pool_capacity_service
from tests.postgresql.business import business


@pytest.mark.parametrize("record_activity", [False, True])
def test_capacity_cache_ignores_connection_reads_and_session_activity(pg_database, business, monkeypatch, record_activity):
    path, service, _, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.resource_pool").fetchone() == (1,)
    now = [1000]
    monkeypatch.setattr(service.policy, "clock", lambda: now[0])
    state = DerivedCacheState()
    cache = PostgresCapacityCache(path.database, path.key, state, lambda: date(2026, 1, 2), access=editor)
    capacity = create_pool_capacity_service(path, access=editor)
    calculations = []

    def calculate(pool_ids, day):
        result = capacity.calculate_many(pool_ids, day)
        calculations.append(result)
        if record_activity:
            now[0] += 1
            service.activity(editor.actor)
        return result

    result = cache.load(calculate, details=True, pool_ids=[1])
    now[0] += 1
    service.activity(editor.actor)
    cached = cache.load(calculate, details=True, pool_ids=[1])
    assert len(calculations) == 1
    assert result == cached and result[0].peak_assigned_fte == 1
    assert len(state.entries) == 1


@pytest.mark.parametrize("revoke_during_calculation", [False, True])
def test_capacity_cache_redacts_staffing_after_shared_permission_is_revoked(pg_database, business, revoke_during_calculation):
    path, service, admin, _, manager = business
    service.grant(admin, admin.user_id, "project_viewer", {"kind": "all"})
    assignment = next(row["id"] for row in service.assignments(admin, admin.user_id) if row["role"] == "business_admin")
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.employee(employee_id,firstname,lastname,email) VALUES(1,'Resource','Person','resource@example.test')")
        connection.execute("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id) VALUES(1,'employee',1)")
    state = DerivedCacheState()
    cache = PostgresCapacityCache(path.database, path.key, state, lambda: date(2026, 1, 2), access=manager)
    capacity = create_pool_capacity_service(path, access=manager)
    calculations = []

    def calculate(pool_ids, day):
        result = capacity.calculate_many(pool_ids, day)
        calculations.append(result)
        if revoke_during_calculation and len(calculations) == 1:
            service.revoke(admin, assignment)
        return result

    result = cache.load(calculate, details=True, pool_ids=[1])
    if not revoke_during_calculation:
        assert result[0].contributing_resources
        service.revoke(admin, assignment)
        result = cache.load(calculate, details=True, pool_ids=[1])
    assert len(calculations) == 2
    assert calculations[0][0].contributing_resources
    assert result[0].contributing_resources == []
    assert result[0].peak_assigned_fte == 3


def test_capacity_cache_missing_revision_fails_before_calculating_or_publishing(pg_database, business):
    path, _, _, editor, _ = business
    state = DerivedCacheState()
    cache = PostgresCapacityCache(path.database, path.key, state, lambda: date(2026, 1, 2), access=editor)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("DELETE FROM eppm.pool_cache_revision")

    def calculate(pool_ids, day):
        pytest.fail("An unavailable revision must not permit a capacity calculation")

    with pytest.raises(ResourcePoolStorageError, match="could not be accessed"):
        cache.load(calculate, details=True, pool_ids=[1])
    assert not state.entries


@pytest.mark.parametrize("table", ["pool_capacity_cache", "pool_cache_revision"])
def test_runtime_capacity_reads_do_not_recreate_missing_storage(pg_database, business, table):
    path, _, _, editor, _ = business
    state = DerivedCacheState()
    cache = PostgresCapacityCache(path.database, path.key, state, lambda: date(2026, 1, 2), access=editor)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute(pg_sql.SQL("DROP TABLE eppm.{} CASCADE").format(pg_sql.Identifier(table)))

    def calculate(pool_ids, day):
        pytest.fail("Missing capacity storage must fail before calculating")

    with pytest.raises(ResourcePoolStorageError, match="could not be accessed"):
        cache.load(calculate, details=True, pool_ids=[1])
    assert not state.entries
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT to_regclass(%s)", ("eppm." + table,)).fetchone() == (None,)


def test_capacity_cache_recomputes_after_a_scope_change_during_calculation(business):
    path, service, admin, editor, _ = business
    state = DerivedCacheState()
    cache = PostgresCapacityCache(path.database, path.key, state, lambda: date(2026, 1, 2), access=editor)
    capacity = create_pool_capacity_service(path, access=editor)
    observed = []

    def calculate(pool_ids, day):
        result = capacity.calculate_many(pool_ids, day)
        observed.append(result[0].peak_assigned_fte)
        if len(observed) == 1:
            service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [2]})
        return result

    result = cache.load(calculate, details=True, pool_ids=[1])
    assert observed == [1, 3]
    assert result[0].peak_assigned_fte == 3
    assert len(state.entries) == 1
    assert json.loads(next(iter(state.entries.values())).raw)["peak_assigned_fte"] == 3


def test_continuously_changing_capacity_inputs_fail_without_publishing_stale_cache_data(pg_database, business):
    path, _, _, editor, _ = business
    state = DerivedCacheState()
    cache = PostgresCapacityCache(path.database, path.key, state, lambda: date(2026, 1, 2), access=editor)
    capacity = create_pool_capacity_service(path, access=editor)
    calculations = []

    def calculate(pool_ids, day):
        result = capacity.calculate_many(pool_ids, day)
        calculations.append(result)
        with psycopg.connect(pg_database.operator_url) as connection:
            connection.execute("UPDATE eppm.resource_pool_assignment SET fte_assigned=fte_assigned+1 WHERE id=1")
        return result

    with pytest.raises(ResourcePoolStorageError, match="changed repeatedly while calculating; please retry"):
        cache.load(calculate, details=True, pool_ids=[1])
    assert len(calculations) == 3 and not state.entries
    result = cache.load(capacity.calculate_many, details=True, pool_ids=[1])
    assert result[0].peak_assigned_fte == 4
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT fte_assigned FROM eppm.resource_pool_assignment WHERE id=2").fetchone() == (2,)


def test_overlapping_pool_pages_and_summary_detail_reads_reuse_scoped_calculations(pg_database, business):
    path, _, _, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(2,'Second pool',2),(3,'Third pool',3)")
    cache = PostgresCapacityCache(path.database, path.key, DerivedCacheState(), lambda: date(2026, 1, 2), access=editor)
    capacity = create_pool_capacity_service(path, access=editor)
    calls = []

    def calculate(pool_ids, day):
        calls.append(pool_ids)
        return capacity.calculate_many(pool_ids, day)

    summaries = cache.load(calculate, pool_ids=[1, 2])
    assert [item.pool_id for item in summaries] == [1, 2]
    assert cache.load(calculate, details=True, pool_ids=[2])[0].pool_id == 2
    assert [item.pool_id for item in cache.load(calculate, pool_ids=[2, 3])] == [2, 3]
    assert [item.pool_id for item in cache.load(calculate, details=True)] == [1, 2, 3]
    assert calls == [[1, 2], [3]]
    # Caller mutation of either projection cannot corrupt the shared pool entry.
    summaries.clear()
    detail = cache.load(calculate, details=True, pool_ids=[1])[0]
    assert detail.daily_usage
    detail.daily_usage.clear()
    assert cache.load(calculate, pool_ids=[1])[0].peak_assigned_fte == 1
    assert cache.load(calculate, details=True, pool_ids=[1])[0].daily_usage
    assert len(calls) == 2


def test_extending_a_pool_cache_discards_warm_values_if_inputs_change_mid_calculation(pg_database, business):
    path, _, _, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(2,'Second pool',2)")
    cache = PostgresCapacityCache(path.database, path.key, DerivedCacheState(), lambda: date(2026, 1, 2), access=editor)
    capacity = create_pool_capacity_service(path, access=editor)
    calls = []

    def calculate(pool_ids, day):
        calls.append(pool_ids)
        result = capacity.calculate_many(pool_ids, day)
        if len(calls) == 2:
            with psycopg.connect(pg_database.operator_url) as connection:
                connection.execute("UPDATE eppm.resource_pool_assignment SET fte_assigned=2 WHERE id=1")
        return result

    assert cache.load(calculate, pool_ids=[1])[0].peak_assigned_fte == 1
    expanded = cache.load(calculate, details=True, pool_ids=[1, 2])
    assert calls == [[1], [2], [1]]
    assert expanded[0].peak_assigned_fte == 2


def test_pool_cache_reuse_never_crosses_current_actor_scope(business):
    path, _, _, editor, manager = business
    state = DerivedCacheState()
    for access, peak in ((manager, 3), (editor, 1), (manager, 3)):
        cache = PostgresCapacityCache(path.database, path.key, state, lambda: date(2026, 1, 2), access=access)
        capacity = create_pool_capacity_service(path, access=access)
        assert cache.load(capacity.calculate_many, pool_ids=[1])[0].peak_assigned_fte == peak
        assert cache.load(capacity.calculate_many, details=True)[0].peak_assigned_fte == peak


def test_capacity_inputs_include_only_projects_consuming_the_requested_pools(pg_database, business):
    from app.infrastructure.postgresql.pool_capacity import PostgresCapacityReader

    path, _, _, editor, manager = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name) VALUES(3,'Unrelated')")
        seed_test_plans(connection)
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (30,3,'Other task','2026-01-01','2026-01-05',(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))")
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(2,'Other pool',1)")
        connection.execute('INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned,project_plan_id) VALUES (2,3,30,1,(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))')
    for access, expected in ((manager, {1, 2}), (editor, {1})):
        reader = PostgresCapacityReader(path.database, path.key, access=access)
        inputs = reader.read([1])
        assert set(inputs) == {1}
        assert set(inputs[1].project_bounds) == expected
        assert {item['project_id'] for item in inputs[1].assignments} == expected
        assert reader.read([]) == {}
