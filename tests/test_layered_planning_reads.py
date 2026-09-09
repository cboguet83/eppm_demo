"""Planning summary consistency, cache atomicity, and portfolio overload rules."""

from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from app.application.exceptions import PlanningConflictError
from app.domain.planning.constraints import evaluate_constraints
from app.domain.resources.models import DailyOverassignment, PoolCapacityDetail
from app.domain.resources.overallocation import overloaded_consumers
from app.infrastructure.database.connection import get_db
from app.operator_services import create_planning_service, create_project_overallocation_service
from app.infrastructure.database.schema_init import init_db


@pytest.fixture
def database(tmp_path: Path) -> str:
    path = str(tmp_path / "summary.db")
    init_db(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executemany(
            "INSERT INTO project(id,name) VALUES(?,?)",
            [(1, "Source"), (2, "Early"), (3, "On time")],
        )
    return path


@pytest.mark.parametrize("link_type", ["FS", "FF", "SS", "SF"])
@pytest.mark.parametrize("lag", [-2, 0, 2])
@pytest.mark.parametrize("whole_project", [False, True])
def test_sql_summary_warnings_match_domain_rules_at_date_boundaries(
    database: str,
    link_type: str,
    lag: int,
    whole_project: bool,
) -> None:
    service = create_planning_service(database)
    predecessor = service.create_milestone(1, "Source task", "", "2026-01-10", "2026-01-20", 0)
    base = date(2026, 1, 10 if link_type in ("SS", "SF") else 20)
    for project_id, early in ((2, 1), (3, 0)):
        boundary = base + timedelta(days=lag - early)
        if link_type in ("FF", "SF"):
            start, end = boundary - timedelta(days=3), boundary
        else:
            start, end = boundary, boundary + timedelta(days=3)
        dependency = (
            {"predecessor_project_id": 1}
            if whole_project
            else {"predecessor_task_id": predecessor}
        )
        service.create_milestone(
            project_id,
            "Successor",
            "",
            start.isoformat(),
            end.isoformat(),
            0,
            dependencies=[{**dependency, "link_type": link_type, "lag_days": lag}],
        )
    tasks = service.get_milestones_for_projects([1, 2, 3])
    _, warnings = evaluate_constraints(
        tasks,
        service.get_dependencies_for_projects([1, 2, 3]),
        service.get_all_project_date_bounds(),
    )
    expected = {task["project_id"]: bool(warnings[task["id"]]) for task in tasks}
    assert expected == {1: False, 2: True, 3: False}
    summaries = service.get_project_summaries([3, 2, 1])
    assert [row["id"] for row in summaries] == [1, 2, 3]
    assert {row["id"]: row["hasViolations"] for row in summaries} == expected
    assert all(row["taskCount"] == 1 for row in summaries)
    assert service.get_project_summaries([1, 2, 3]) == summaries


def test_failed_summary_fill_rolls_back_all_cache_rows_and_closes_connection(
    database: str,
) -> None:
    service = create_planning_service(database)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("""CREATE TRIGGER reject_summary BEFORE INSERT ON planning_summary_cache
            WHEN NEW.project_id=2 BEGIN SELECT RAISE(ABORT,'internal cache error'); END""")
    held = get_db(database)
    with patch("app.infrastructure.repositories.planning.get_db", return_value=held):
        with pytest.raises(PlanningConflictError):
            service.get_project_summaries([1, 2, 3])
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        held.execute("SELECT 1")
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM planning_summary_cache").fetchone()[0] == 0
    assert service.get_project_summaries([]) == []


def test_summary_fill_reserves_writer_until_projection_is_published(database: str) -> None:
    service = create_planning_service(database)
    attempts = []
    held = get_db(database)

    def compete(statement: str) -> None:
        if statement.startswith("WITH scope"):
            with closing(sqlite3.connect(database, timeout=0)) as competitor:
                try:
                    competitor.execute("UPDATE project SET name='Concurrent' WHERE id=1")
                except sqlite3.OperationalError as exc:
                    attempts.append(str(exc))

    held.set_trace_callback(compete)
    with patch("app.infrastructure.repositories.planning.get_db", return_value=held):
        rows = service.get_project_summaries([1])
    assert attempts == ["database is locked"]
    assert rows[0]["name"] == "Source"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE project SET name='Concurrent' WHERE id=1")
    assert service.get_project_summaries([1])[0]["name"] == "Concurrent"


def test_failed_task_edit_restores_summary_cache_and_reports_only_affected_projects(
    database: str,
) -> None:
    service = create_planning_service(database)
    first = service.create_milestone(1, "Source", "", "2026-01-01", "2026-01-10", 0)
    service.create_milestone(
        2,
        "Task successor",
        "",
        "2026-01-05",
        "2026-01-05",
        0,
        dependencies=[{"predecessor_task_id": first}],
    )
    service.create_milestone(
        3,
        "Project successor",
        "",
        "2026-01-05",
        "2026-01-05",
        0,
        dependencies=[{"predecessor_project_id": 1}],
    )
    summaries = service.get_project_summaries([1, 2, 3])
    with pytest.raises(PlanningConflictError):
        service.update_milestone(
            first,
            "Failed edit",
            "",
            "2026-01-01",
            "2026-01-02",
            0,
            dependencies=[{"predecessor_task_id": 999}],
        )
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM planning_summary_cache").fetchone()[0] == 3
    assert service.get_project_summaries([1, 2, 3]) == summaries
    assert service.affected_task_projects(first) == ({1, 2, 3}, set())
    assert service.affected_task_projects(999) == (set(), set())
    assert (
        create_project_overallocation_service(database).overallocated_project_ids([1, 2, 3])
        == set()
    )


def test_summary_schema_installs_idempotently_on_an_existing_database(database: str) -> None:
    from app.infrastructure.database.schema_init import init_db

    init_db(database)
    init_db(database)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='planning_summary_cache'"
        ).fetchall()
    service = create_planning_service(database)
    assert len(service.get_project_summaries([1, 2, 3])) == 3
    with closing(sqlite3.connect(database)) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'planning_summary_%'"
            ).fetchone()[0]
            == 9
        )


def test_overload_rule_ignores_undated_zero_and_unrequested_assignments() -> None:
    pool = PoolCapacityDetail(
        pool_id=1,
        pool_name="Pool",
        total_capacity_fte=1,
        peak_assigned_fte=2,
        total_assigned_fte_scalar=2,
        is_overassigned=True,
        peak_excess_fte=1,
        daily_overassignments=[DailyOverassignment("2026-01-02", 1, 2, 1)],
        assignments=[
            {"project_id": 1, "fte_assigned": 1, "start_date": None, "end_date": None},
            {
                "project_id": 2,
                "fte_assigned": 0,
                "start_date": "2026-01-01",
                "end_date": "2026-01-03",
            },
            {
                "project_id": 3,
                "fte_assigned": 1,
                "start_date": "2026-01-01",
                "end_date": "2026-01-03",
            },
            {
                "project_id": 4,
                "fte_assigned": 1,
                "start_date": "2026-01-02",
                "end_date": "2026-01-02",
            },
        ],
    )
    assert overloaded_consumers([pool], {1, 2, 4}) == {4}
