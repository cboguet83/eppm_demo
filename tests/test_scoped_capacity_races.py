"""Capacity caching discards results when persisted access or inputs change mid-read."""

from contextlib import closing
from datetime import date

import pytest

from app.application.exceptions import ResourcePoolStorageError
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.pool_capacity_cache import CapacityCacheState, SqliteCapacityCache
from app.main import create_pool_capacity_service
from tests.test_business_transaction_security import business as business


@pytest.mark.parametrize("journal_mode", ["DELETE", "WAL"])
@pytest.mark.parametrize("record_activity", [False, True])
def test_capacity_cache_ignores_journal_lifecycle_and_session_activity(business, monkeypatch, journal_mode, record_activity):
    path, service, _, editor, _ = business
    with closing(get_db(path)) as connection:
        assert connection.execute(f"PRAGMA journal_mode={journal_mode}").fetchone()[0].upper() == journal_mode
    now = [1000]
    monkeypatch.setattr(service.policy, "clock", lambda: now[0])
    state = CapacityCacheState()
    cache = SqliteCapacityCache(path, state, lambda: date(2026, 1, 2), access=editor)
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
def test_capacity_cache_redacts_staffing_after_shared_permission_is_revoked(business, revoke_during_calculation):
    path, service, admin, _, manager = business
    service.grant(admin, admin.user_id, "project_viewer", {"kind": "all"})
    assignment = next(row["id"] for row in service.assignments(admin, admin.user_id) if row["role"] == "business_admin")
    with closing(get_db(path)) as connection, connection:
        connection.execute("INSERT INTO employee(employee_id,firstname,lastname,email,employee_code) VALUES(1,'Resource','Person','resource@example.test','RES1')")
        connection.execute("INSERT INTO resource_pool_mapping(pool_id,target_type,target_id) VALUES(1,'employee',1)")
    state = CapacityCacheState()
    cache = SqliteCapacityCache(path, state, lambda: date(2026, 1, 2), access=manager)
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


def test_capacity_cache_missing_revision_fails_before_calculating_or_publishing(business):
    path, _, _, editor, _ = business
    state = CapacityCacheState()
    cache = SqliteCapacityCache(path, state, lambda: date(2026, 1, 2), access=editor)
    with closing(get_db(path)) as connection, connection:
        connection.execute("DELETE FROM pool_capacity_revision")

    def calculate(pool_ids, day):
        pytest.fail("An unavailable revision must not permit a capacity calculation")

    with pytest.raises(ResourcePoolStorageError, match="capacity revision is unavailable"):
        cache.load(calculate, details=True, pool_ids=[1])
    assert not state.entries


@pytest.mark.parametrize("upgrade", ["migration", "operator_cache"])
def test_database_upgrade_installs_capacity_revisions_without_changing_business_or_access_records(business, upgrade):
    from app.infrastructure.database.schema_init import init_db

    path, _, _, _, _ = business
    tables = ("project", "project_task", "resource_pool_assignment", "app_user", "app_identity", "app_role_assignment", "app_session", "app_security_state")
    with closing(get_db(path)) as connection, connection:
        # Earlier installations created derived capacity storage only on an
        # operator cache read. Model that absence without altering access guards.
        triggers = connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'capacity_*'").fetchall()
        for name, in triggers:
            connection.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        for table in ("pool_capacity_revision", "pool_capacity_cache", "pool_capacity_employee"):
            connection.execute(f"DROP TABLE {table}")
        before = {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in tables}
    if upgrade == "operator_cache":
        from app.operator_services import create_pool_capacity_service as create_operator_capacity

        assert len(create_operator_capacity(path).get_summaries()) == 1
    else:
        init_db(path)
    with closing(get_db(path)) as connection:
        revision = connection.execute("SELECT epoch,revision FROM pool_capacity_revision WHERE id=1").fetchone()
        assert revision and revision[1] == 0
        assert {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in tables} == before
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    init_db(path)
    with closing(get_db(path)) as connection, connection:
        assert connection.execute("SELECT epoch,revision FROM pool_capacity_revision WHERE id=1").fetchone() == revision
        connection.execute("UPDATE resource_pool_assignment SET fte_assigned=2 WHERE id=1")
        assert connection.execute("SELECT revision FROM pool_capacity_revision WHERE id=1").fetchone()[0] == 1


def test_capacity_cache_recomputes_after_a_scope_change_during_calculation(business):
    path, service, admin, editor, _ = business
    state = CapacityCacheState()
    cache = SqliteCapacityCache(path, state, lambda: date(2026, 1, 2), access=editor)
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
    assert next(iter(state.entries.values()))[0].peak_assigned_fte == 3


def test_continuously_changing_capacity_inputs_fail_without_publishing_stale_cache_data(business):
    path, _, _, editor, _ = business
    state = CapacityCacheState()
    cache = SqliteCapacityCache(path, state, lambda: date(2026, 1, 2), access=editor)
    capacity = create_pool_capacity_service(path, access=editor)
    calculations = []

    def calculate(pool_ids, day):
        result = capacity.calculate_many(pool_ids, day)
        calculations.append(result)
        with closing(get_db(path)) as connection, connection:
            connection.execute("UPDATE resource_pool_assignment SET fte_assigned=fte_assigned+1 WHERE id=1")
        return result

    with pytest.raises(ResourcePoolStorageError, match="changed while calculating capacity; please retry"):
        cache.load(calculate, details=True, pool_ids=[1])
    assert len(calculations) == 3 and not state.entries
    result = cache.load(capacity.calculate_many, details=True, pool_ids=[1])
    assert result[0].peak_assigned_fte == 4
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT fte_assigned FROM resource_pool_assignment WHERE id=2").fetchone() == (2,)
