"""Planning summary consistency, cache atomicity, and portfolio overload rules."""

from datetime import date, timedelta
from unittest.mock import patch

import psycopg
import pytest

from app.application.exceptions import PlanningConflictError, PlanningStorageError
from app.application.ports.planning import ProjectSummary
from app.application.services.business_access import BusinessAccess
from app.domain.planning.constraints import evaluate_constraints
from app.domain.resources.models import DailyOverassignment, PoolCapacityDetail
from app.domain.resources.overallocation import overloaded_consumers
from app.infrastructure.postgresql.derived_cache import PostgresDerivedCache
from app.infrastructure.postgresql.migration import migrate
from app.infrastructure.postgresql.planning import PostgresPlanningStore
from app.main import create_planning_service, create_project_overallocation_service
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access


@pytest.fixture
def database(runtime: RuntimeResources, authorized: AuthorizedFixture) -> RuntimeResources:
    """Name the three visible fixture projects for boundary comparisons."""
    with psycopg.connect(authorized.setup.operator_url) as connection, connection.cursor() as cursor:
        cursor.executemany(
            "UPDATE eppm.project SET name=%s WHERE id=%s",
            [("Source", 1), ("Early", 2), ("On time", 3)],
        )
    return runtime


@pytest.mark.parametrize("link_type", ["FS", "FF", "SS", "SF"])
@pytest.mark.parametrize("lag", [-2, 0, 2])
@pytest.mark.parametrize("whole_project", [False, True])
def test_sql_summary_warnings_match_domain_rules_at_date_boundaries(
    database: RuntimeResources,
    access: BusinessAccess,
    link_type: str,
    lag: int,
    whole_project: bool,
) -> None:
    service = create_planning_service(database, access=access)
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


def test_failed_summary_fill_rolls_back_all_cache_rows_and_returns_usable_leases(
    database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    service = create_planning_service(database, access=access)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_test_summary() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
                IF NEW.project_id=2 THEN
                    RAISE EXCEPTION 'internal cache error' USING ERRCODE='23514';
                END IF;
                RETURN NEW;
            END $$""")
        connection.execute("""CREATE TRIGGER reject_summary BEFORE INSERT
            ON eppm.planning_summary_cache FOR EACH ROW
            EXECUTE FUNCTION eppm.reject_test_summary()""")
    with pytest.raises(PlanningStorageError) as caught:
        service.get_project_summaries([1, 2, 3])
    assert caught.value.__cause__ is None
    assert "internal cache error" not in str(caught.value)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT COUNT(*) FROM eppm.planning_summary_cache").fetchone()[0] == 0
        connection.execute("DROP TRIGGER reject_summary ON eppm.planning_summary_cache")
    assert service.get_project_summaries([]) == []
    assert len(service.get_project_summaries([1, 2, 3])) == 3


def test_summary_fill_recalculates_after_a_concurrent_commit_before_publication(
    database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    service = create_planning_service(database, access=access)
    original = PostgresPlanningStore.get_project_summaries
    calculated_names: list[str] = []

    def compete(store: PostgresPlanningStore, project_ids: list[int]) -> list[ProjectSummary]:
        rows = original(store, project_ids)
        calculated_names.append(rows[0]["name"])
        if len(calculated_names) == 1:
            with psycopg.connect(authorized.setup.operator_url) as competitor:
                competitor.execute("SET LOCAL statement_timeout='1s'")
                competitor.execute("UPDATE eppm.project SET name='Concurrent' WHERE id=1")
            # The original read transaction retains its pre-commit snapshot.
            assert original(store, project_ids)[0]["name"] == "Source"
        return rows

    with patch.object(PostgresPlanningStore, "get_project_summaries", compete):
        rows = service.get_project_summaries([1])
        assert calculated_names == ["Source", "Concurrent"]
        assert rows[0]["name"] == "Concurrent"
        assert service.get_project_summaries([1]) == rows
        assert calculated_names == ["Source", "Concurrent"]


def test_failed_task_edit_restores_summary_cache_and_reports_only_affected_projects(
    database: RuntimeResources,
    access: BusinessAccess,
) -> None:
    service = create_planning_service(database, access=access)
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
    cache = PostgresDerivedCache(database.database, database.key, database.caches, access=access)
    current = cache.read("planning", [1, 2, 3], date(2000, 1, 1), False, [])
    assert len(current) == 3 and all(row[3] for row in current)
    assert service.get_project_summaries([1, 2, 3]) == summaries
    assert service.affected_task_projects(first) == ({1, 2, 3}, set())
    assert service.affected_task_projects(999) == (set(), set())
    assert (
        create_project_overallocation_service(database, access=access).overallocated_project_ids([1, 2, 3])
        == set()
    )


def test_summary_schema_reentry_preserves_existing_cache_and_trigger_definitions(
    database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    service = create_planning_service(database, access=access)
    summaries = service.get_project_summaries([1, 2, 3])
    cache = PostgresDerivedCache(database.database, database.key, database.caches, access=access)
    before = cache.read("planning", [1, 2, 3], date(2000, 1, 1), False, [])
    trigger_query = """SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid)
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='eppm' AND NOT t.tgisinternal ORDER BY 1,2"""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        triggers = connection.execute(trigger_query).fetchall()
    assert triggers
    assert len(before) == 3 and all(row[3] for row in before)

    migrate(authorized.setup.operator_url)
    migrate(authorized.setup.operator_url)

    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute(trigger_query).fetchall() == triggers
    assert cache.read("planning", [1, 2, 3], date(2000, 1, 1), False, []) == before
    assert service.get_project_summaries([1, 2, 3]) == summaries


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
