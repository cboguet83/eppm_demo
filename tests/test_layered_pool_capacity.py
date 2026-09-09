"""Pure capacity boundaries, batched snapshots, and concurrent cache publication."""

from contextlib import closing
from dataclasses import asdict
from datetime import date
from pathlib import Path
import sqlite3
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
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.pool_capacity_cache import CapacityCacheState, SqliteCapacityCache
from app.infrastructure.repositories.pool_capacity import SqliteCapacityReader
from app.infrastructure.database.schema_init import init_db

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
def database(tmp_path: Path) -> str:
    path = str(tmp_path / "capacity.db")
    init_db(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("INSERT INTO project(id,name) VALUES(1,'No dates')")
        connection.executemany(
            "INSERT INTO resource_pool(id,name,capacity_fte) VALUES(?,?,?)",
            [(1, "A", 2), (2, "B", 3)],
        )
        connection.execute(
            "INSERT INTO resource_pool_assignment(pool_id,project_id,fte_assigned) VALUES(1,1,1)"
        )
    return path


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
    database: str,
) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    queries = []
    changed = False

    def traced_connection(path: str) -> sqlite3.Connection:
        connection = get_db(path)

        def trace(sql: str) -> None:
            nonlocal changed
            queries.append(sql)
            if "FROM team_function" in sql and not changed:
                changed = True
                with closing(sqlite3.connect(path)) as writer, writer:
                    writer.execute("UPDATE resource_pool SET name='Changed' WHERE id=1")
                    writer.execute(
                        "UPDATE resource_pool_assignment SET fte_assigned=2 WHERE pool_id=1"
                    )

        connection.set_trace_callback(trace)
        return connection

    with patch("app.infrastructure.repositories.resource_pools.get_db", traced_connection):
        snapshot = SqliteCapacityReader(database).read([1, 2])
        two_pool_queries = len(queries)
        queries.clear()
        next_snapshot = SqliteCapacityReader(database).read([1])
    assert len(queries) == two_pool_queries
    assert snapshot[1].pool.name == "A" and snapshot[1].assignments[0]["fte_assigned"] == 1
    assert (
        next_snapshot[1].pool.name == "Changed"
        and next_snapshot[1].assignments[0]["fte_assigned"] == 2
    )
    assert snapshot[1].functions is snapshot[2].functions


def test_cache_rejects_stale_publication_and_preserves_explicit_calculation_day(
    database: str,
) -> None:
    state = CapacityCacheState()
    cache = SqliteCapacityCache(database, state, lambda: DAY)
    service = PoolCapacityService(SqliteCapacityReader(database), cache, lambda: DAY)
    calls = []

    def calculate(ids: list[int], day: date):
        details = service.calculate_many(ids, day)
        calls.append((ids, day))
        if len(calls) == 1:
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    "UPDATE resource_pool_assignment SET fte_assigned=4 WHERE pool_id=1"
                )
        return details

    detail = cache.load(calculate, details=True, pool_ids=[1])[0]
    assert calls == [([1], DAY), ([1], DAY)]
    assert detail.daily_usage == {"2026-09-08": 4}
    assert project_pool_status(1, detail)["excess_fte"] == 2
    assert project_pool_status(99, detail)["assignments_count"] == 0
    state.entries.clear()
    with patch.object(
        service, "calculate_many", side_effect=AssertionError("warm disk cache recalculated")
    ):
        assert asdict(service.get_details([1])[0]) == asdict(detail)
        assert service.get_summaries([1])[0].is_overassigned
        assert service.get_summaries([]) == []
    next_cache = SqliteCapacityCache(database, state, lambda: date(2026, 9, 9))
    tomorrow = next_cache.load(service.calculate_many, details=True, pool_ids=[1])[0]
    assert tomorrow.daily_usage == {"2026-09-09": 4}


def test_cache_reports_repeated_edits_safely_without_publishing_stale_rows(database: str) -> None:
    cache = SqliteCapacityCache(database, CapacityCacheState(), lambda: DAY)
    service = PoolCapacityService(SqliteCapacityReader(database), cache, lambda: DAY)

    def changing(ids: list[int], day: date):
        details = service.calculate_many(ids, day)
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("UPDATE resource_pool SET capacity_fte=capacity_fte+1 WHERE id=1")
        return details

    with pytest.raises(ResourcePoolStorageError, match="changed repeatedly"):
        cache.load(changing, pool_ids=[1])
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pool_capacity_cache").fetchone()[0] == 0


def test_cache_translates_storage_failures_and_bounds_process_memory(database: str) -> None:
    state = CapacityCacheState()
    cache = SqliteCapacityCache(database, state, lambda: DAY)
    service = PoolCapacityService(SqliteCapacityReader(database), cache, lambda: DAY)
    for day in range(1, 11):
        cache.today = lambda day=day: date(2026, 9, day)
        service.get_summaries([1])
    assert len(state.entries) == 8
    with patch(
        "app.infrastructure.database.pool_capacity_cache.get_db",
        side_effect=sqlite3.OperationalError("internal path"),
    ):
        with pytest.raises(ResourcePoolStorageError) as failure:
            service.get_summaries([1])
    assert "internal path" not in str(failure.value)
    assert isinstance(failure.value.__cause__, sqlite3.OperationalError)
