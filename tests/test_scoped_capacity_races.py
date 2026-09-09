"""Capacity caching discards results when persisted access or inputs change mid-read."""

from contextlib import closing
from datetime import date

import pytest

from app.application.exceptions import ResourcePoolStorageError
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.pool_capacity_cache import CapacityCacheState, SqliteCapacityCache
from app.main import create_pool_capacity_service
from tests.test_business_transaction_security import business as business


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
