"""Pure capacity boundaries, batched snapshots, and concurrent cache publication."""

from dataclasses import asdict
from datetime import date
import psycopg
from psycopg.conninfo import conninfo_to_dict
from unittest.mock import patch

import pytest

from app.application.exceptions import ResourcePoolStorageError
from app.application.services.pool_capacity import PoolCapacityService
from app.domain.organization.models import Employee, EmployeeCalendarException, OrgFunction, Team
from app.domain.resources.capacity import (
    calculate_capacity,
    resolve_assignments,
    resource_contributions,
)
from app.domain.resources.capacity_rules import (
    accumulate_daily_usage,
    calculate_daily_overassignments,
    get_projects_consuming_pool_in_period,
    group_date_intervals,
    project_pool_status,
)
from app.domain.resources.inputs import CapacityInputs
from app.domain.resources.models import DailyOverassignment, PoolMapping, ResourcePool
from app.infrastructure.postgresql.capacity_cache import PostgresCapacityCache
from app.infrastructure.postgresql.derived_cache import DerivedCacheState
from app.infrastructure.postgresql.pool_capacity import PostgresCapacityReader
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolStore
from app.application.services.business_access import BusinessAccess
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access

DAY = date(2026, 9, 8)


def test_capacity_keeps_historical_rounding_order_at_half_millifte_boundary() -> None:
    inputs = CapacityInputs(
        1,
        functions=[OrgFunction("Part-time", 1, function_id=1, fte_percentage=1)],
        mappings=[PoolMapping(1, "function", 1, 35)],
    )
    # Dividing the mapping percentage first is the established calculation.
    # Reordering multiplication/division changes this result to 0.004.
    detail = calculate_capacity(inputs, DAY)
    assert detail.assigned_capacity_fte == 0.003
    assert detail.contributing_resources[0].effective_fte == 0.003


@pytest.fixture
def database(runtime: RuntimeResources, authorized: AuthorizedFixture) -> RuntimeResources:
    """Seed date-free demand through the separate fixture operator connection."""
    with psycopg.connect(authorized.setup.operator_url) as connection, connection.cursor() as cursor:
        connection.execute("UPDATE eppm.project SET name='No dates' WHERE id=1")
        cursor.executemany(
            "INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(%s,%s,%s)",
            [(1, "A", 2), (2, "B", 3)],
        )
        connection.execute(
            'INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,project_plan_id) VALUES (1,1,1,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))'
        )
    return runtime


def test_direct_override_zero_capacity_and_vacant_function_fallback() -> None:
    inputs = CapacityInputs(
        1,
        pool=ResourcePool("Pool", capacity_fte=10),
        functions=[
            OrgFunction("Manager", 1, function_id=1),
            OrgFunction("Vacant", 2, function_id=2, manager_function_id=1, fte_percentage=200),
        ],
        teams=[Team("Small team", team_id=1, manager_function_id=1)],
        employees=[
            Employee("Ada", "Lovelace", "ada@example.invalid", "ADA", employee_id=1, function_id=1)
        ],
        mappings=[
            PoolMapping(1, "team", 1, 50),
            PoolMapping(1, "function", 1, 20),
            PoolMapping(1, "employee", 1, 0),
            PoolMapping(1, "employee", 99),
            PoolMapping(1, "function", 99),
        ],
        exceptions=[EmployeeCalendarException(99, DAY, DAY, 0)],
    )
    contributions = resource_contributions(inputs)
    assert [(item.resource_id, item.effective_fte) for item in contributions] == [(1, 0), (2, 1)]
    assert (
        contributions[0].is_deduplicated
        and contributions[0].source_name == "Direct Employee Mapping"
    )
    detail = calculate_capacity(inputs, DAY)
    assert detail.total_capacity_fte == 10 and detail.effective_capacity_fte == 1
    inputs.mappings = [PoolMapping(1, "employee", 1, 0)]
    detail = calculate_capacity(inputs, DAY)
    assert detail.has_assigned_resources and detail.effective_capacity_fte == 0
    assert detail.peak_assigned_fte == 0


def test_assignment_dates_resolve_each_endpoint_before_today_fallback() -> None:
    rows = [
        dict(
            id=1,
            project_id=1,
            task_id=7,
            task_name="Build",
            fte_assigned=2,
            custom_start_date="2026-09-02",
            task_end_date="2026-09-05",
        ),
        dict(id=2, project_id=2, task_id=None, fte_assigned=1),
        dict(id=3, project_id=3, task_id=None, fte_assigned=1, custom_end_date="2026-09-09"),
    ]
    inputs = CapacityInputs(1, assignments=rows, project_bounds={2: ("2026-09-01", "2026-09-03")})
    resolved = resolve_assignments(inputs, DAY)
    assert [(row["start_date"], row["end_date"]) for row in resolved] == [
        ("2026-09-02", "2026-09-05"),
        ("2026-09-01", "2026-09-03"),
        ("2026-09-08", "2026-09-09"),
    ]
    assert resolved[0]["is_custom_period"] and not resolved[1]["is_custom_period"]
    assert rows[1].get("start_date") is None
    assert get_projects_consuming_pool_in_period(resolved, "", "2026-09-08") == []
    assert get_projects_consuming_pool_in_period(
        resolved + [dict(project_id=9, fte_assigned=1)], "2026-09-08", "2026-09-08"
    ) == [3]


def test_overassignment_intervals_preserve_gaps_peak_and_invalid_date_handling() -> None:
    usage = {"2026-09-01": 2, "2026-09-02": 3, "2026-09-04": 2, "2026-09-06": 1}
    over = calculate_daily_overassignments(usage, 1)
    assert group_date_intervals(over) == [
        "2026-09-01 to 2026-09-02 (+2.00 FTE)",
        "2026-09-04 (+1.00 FTE)",
    ]
    assert group_date_intervals(
        over + [DailyOverassignment("bad", 1, 2, 1)]
    ) == group_date_intervals(over)
    days = {}
    accumulate_daily_usage(days, "invalid", "invalid", 1)
    assert days == {}
    accumulate_daily_usage(days, "2026-09-02", "2026-09-01", 1)
    assert days == {"2026-09-02": 1}
    accumulate_daily_usage(days, "2000-01-01", "2099-01-01", 0)
    assert len(days) == 365 * 25 + 1


def test_snapshot_reader_uses_constant_queries_and_keeps_concurrent_versions_separate(
    database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    """Count real driver queries and commit a writer between snapshot reads."""
    queries = []
    changed = False
    runtime_login = conninfo_to_dict(authorized.setup.runtime_url)['user']
    execute = psycopg.Cursor.execute
    assignments = PostgresResourcePoolStore.get_assignments

    def trace(cursor, query, params=None, **kwargs):
        # The login inherits eppm_runtime; pool reset statements can run in a
        # worker, so count actual read queries rather than connection cleanup.
        if (
            cursor.connection.info.user == runtime_login
            and isinstance(query, str)
            and query.lstrip().startswith('SELECT ')
        ):
            queries.append(query)
        return execute(cursor, query, params, **kwargs)

    def interleaved_assignments(store, *args, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            with psycopg.connect(authorized.setup.operator_url) as writer:
                writer.execute("UPDATE eppm.resource_pool SET name='Changed' WHERE id=1")
                writer.execute("UPDATE eppm.resource_pool_assignment SET fte_assigned=2 WHERE pool_id=1")
        return assignments(store, *args, **kwargs)

    reader = PostgresCapacityReader(database.database, database.key, access=access)
    with patch.object(psycopg.Cursor, 'execute', autospec=True, side_effect=trace), \
            patch.object(PostgresResourcePoolStore, 'get_assignments', autospec=True, side_effect=interleaved_assignments):
        snapshot = reader.read([1, 2])
        two_pool_queries = len(queries)
        queries.clear()
        next_snapshot = reader.read([1])
    assert two_pool_queries > 0 and len(queries) == two_pool_queries
    assert snapshot[1].pool.name == "A" and snapshot[1].assignments[0]["fte_assigned"] == 1
    assert next_snapshot[1].pool.name == "Changed" and next_snapshot[1].assignments[0]["fte_assigned"] == 2
    assert snapshot[1].project_bounds is snapshot[2].project_bounds
    assert snapshot[1].employees == snapshot[2].employees == []


def test_cache_rejects_stale_publication_and_preserves_explicit_calculation_day(
    database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    state = DerivedCacheState()
    cache = PostgresCapacityCache(database.database, database.key, state, lambda: DAY, access=access)
    service = PoolCapacityService(PostgresCapacityReader(database.database, database.key, access=access), cache, lambda: DAY)
    calls = []

    def calculate(ids: list[int], day: date):
        details = service.calculate_many(ids, day)
        calls.append((ids, day))
        if len(calls) == 1:
            with psycopg.connect(authorized.setup.operator_url) as connection:
                connection.execute(
                    "UPDATE eppm.resource_pool_assignment SET fte_assigned=4 WHERE pool_id=1"
                )
        return details

    detail = cache.load(calculate, details=True, pool_ids=[1])[0]
    assert calls == [([1], DAY), ([1], DAY)]
    assert detail.daily_usage == {"2026-09-08": 4}
    assert project_pool_status(1, detail)["excess_fte"] == 2
    assert project_pool_status(99, detail)["assignments_count"] == 0
    cache.cache.state = DerivedCacheState()
    with patch.object(
        service, "calculate_many", side_effect=AssertionError("warm disk cache recalculated")
    ):
        assert asdict(service.get_details([1])[0]) == asdict(detail)
        assert service.get_summaries([1])[0].is_overassigned
        assert service.get_summaries([]) == []
    next_cache = PostgresCapacityCache(database.database, database.key, state, lambda: date(2026, 9, 9), access=access)
    tomorrow = next_cache.load(service.calculate_many, details=True, pool_ids=[1])[0]
    assert tomorrow.daily_usage == {"2026-09-09": 4}


def test_cache_reports_repeated_edits_safely_without_publishing_stale_rows(database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> None:
    cache = PostgresCapacityCache(database.database, database.key, DerivedCacheState(), lambda: DAY, access=access)
    service = PoolCapacityService(PostgresCapacityReader(database.database, database.key, access=access), cache, lambda: DAY)

    def changing(ids: list[int], day: date):
        details = service.calculate_many(ids, day)
        with psycopg.connect(authorized.setup.operator_url) as connection:
            connection.execute("UPDATE eppm.resource_pool SET capacity_fte=capacity_fte+1 WHERE id=1")
        return details

    with pytest.raises(ResourcePoolStorageError, match="changed repeatedly"):
        cache.load(changing, pool_ids=[1])
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT COUNT(*) FROM eppm.pool_capacity_cache").fetchone()[0] == 0


def test_cache_translates_storage_failures_and_bounds_process_memory(
    database: RuntimeResources, access: BusinessAccess, caplog: pytest.LogCaptureFixture,
) -> None:
    """Bound native memory across dates and fail safely before reusing warm data."""
    state = DerivedCacheState(max_entries=8)
    cache = PostgresCapacityCache(database.database, database.key, state, lambda: DAY, access=access)
    service = PoolCapacityService(PostgresCapacityReader(database.database, database.key, access=access), cache, lambda: DAY)
    for day in range(1, 11):
        cache.today = lambda day=day: date(2026, 9, day)
        service.get_summaries([1])
    assert len(state.entries) == 8
    assert state.size_bytes == sum(len(entry.raw) for entry in state.entries.values()) <= state.max_bytes
    database.database.close()
    with pytest.raises(ResourcePoolStorageError) as failure:
        service.get_summaries([1])
    assert 'postgresql://' not in str(failure.value) + caplog.text
    assert failure.value.__cause__ is None
