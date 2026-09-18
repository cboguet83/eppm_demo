"""Display caches survive session activity but reauthorize every lookup."""

from unittest.mock import patch

import psycopg
from psycopg import sql as pg_sql
import pytest
from streamlit.testing.v1 import AppTest

from app.domain.access.models import AccessDenied
from app.infrastructure.postgresql.portfolio import PostgresPortfolioReader
from app.infrastructure.postgresql.migration import migrate
from app.presentation.components.authorized_cache import authorized_cache
from tests.postgresql.business import business


def test_display_revision_is_stable_across_reads_and_session_activity(business, monkeypatch):
    path, service, _, editor, _ = business
    now = [1000]
    monkeypatch.setattr(service.policy, "clock", lambda: now[0])
    reader = PostgresPortfolioReader(path.database, path.key, access=editor)
    before = reader.revision()

    assert reader.revision() == before
    now[0] += 1
    service.activity(editor.actor)
    assert reader.revision() == before


@pytest.mark.parametrize("change", ["logout", "disabled", "revoked", "expired"])
def test_old_display_cache_keys_recheck_session_and_read_permission(business, monkeypatch, change):
    path, service, admin, editor, _ = business
    reader = PostgresPortfolioReader(path.database, path.key, access=editor)
    calculations = []

    @authorized_cache(show_spinner=False)
    def load(revision, _service):
        calculations.append(1)
        return "authorized result"

    before = reader.revision()
    assert load(before, reader) == "authorized result"
    if change == "logout":
        service.logout(editor.actor)
    elif change == "disabled":
        service.set_status(admin, editor.actor.user_id, "disabled")
    elif change == "revoked":
        assignment = service.assignments(admin, editor.actor.user_id)[0]
        service.revoke(admin, assignment["id"])
    else:
        monkeypatch.setattr(service.policy, "clock", lambda: 200000)

    with pytest.raises(AccessDenied):
        load(before, reader)
    assert len(calculations) == 1


def test_permission_change_invalidates_display_with_unchanged_read_scope(business):
    path, service, admin, _, manager = business
    service.grant(admin, admin.user_id, "project_viewer", {"kind": "all"})
    reader = PostgresPortfolioReader(path.database, path.key, access=manager)
    before = reader.revision()
    assignment = next(row["id"] for row in service.assignments(admin, admin.user_id) if row["role"] == "business_admin")

    service.revoke(admin, assignment)

    after = reader.revision()
    assert after[1:] == before[1:]
    assert after != before


@pytest.mark.parametrize("sql", [
    "UPDATE eppm.project SET name='Renamed' WHERE id=1",
    "UPDATE eppm.project_task SET end_date='2026-01-07' WHERE id=10",
    "UPDATE eppm.resource_pool_assignment SET fte_assigned=2 WHERE id=1",
    "UPDATE eppm.schema_parameters SET param_name='Renamed' WHERE param_id='DEPT'",
    "UPDATE eppm.project_property_value SET text_value='Delivery' WHERE project_id=1",
    "DELETE FROM eppm.task_dependencies",
])
def test_display_revision_tracks_committed_business_changes_and_ignores_rollbacks(pg_database, business, sql):
    path, _, _, editor, _ = business
    reader = PostgresPortfolioReader(path.database, path.key, access=editor)
    before = reader.revision()
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute(sql)
        connection.rollback()
    assert reader.revision() == before

    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute(sql)
    assert reader.revision() != before


def test_display_revision_ignores_persisted_derived_cache_writes(pg_database, business):
    from app.main import create_planning_service, create_pool_capacity_service

    path, _, _, editor, _ = business
    reader = PostgresPortfolioReader(path.database, path.key, access=editor)
    before = reader.revision()

    assert create_planning_service(path, access=editor).get_project_summaries([1])
    assert create_pool_capacity_service(path, access=editor).get_details([1])

    assert reader.revision() == before
    with psycopg.connect(pg_database.operator_url) as connection:
        for table in ("planning_summary_cache", "pool_capacity_cache"):
            assert connection.execute(pg_sql.SQL("SELECT count(*) FROM eppm.{}").format(pg_sql.Identifier(table))).fetchone()[0] > 0


def test_repeated_operator_migrations_preserve_business_records_and_revision(pg_database, business):
    path, _, _, editor, _ = business
    reader = PostgresPortfolioReader(path.database, path.key, access=editor)
    revision = reader.revision()

    def records():
        with psycopg.connect(pg_database.operator_url) as connection:
            tables = [row[0] for row in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='eppm' ORDER BY tablename")]
            return {table: connection.execute(pg_sql.SQL(
                "SELECT md5(coalesce(string_agg(to_jsonb(row)::text, '' ORDER BY to_jsonb(row)::text), '')) FROM eppm.{} row"
            ).format(pg_sql.Identifier(table))).fetchone()[0] for table in tables}

    before = records()
    migrate(pg_database.operator_url)
    migrate(pg_database.operator_url)
    assert reader.revision() == revision
    assert records() == before


@pytest.mark.parametrize("missing", ["row", "table"])
def test_missing_display_revision_fails_safely(pg_database, business, missing):
    from app.application.exceptions import ProjectStorageError

    path, _, _, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("DELETE FROM eppm.catalog_cache_revision" if missing == "row" else "DROP TABLE eppm.catalog_cache_revision CASCADE")
    with pytest.raises(ProjectStorageError):
        PostgresPortfolioReader(path.database, path.key, access=editor).revision()


def test_portfolio_paging_keeps_context_and_requested_offset_after_activity(pg_database, business, monkeypatch):
    from tests.test_fragment_reruns import portfolio_app

    path, service, _, _, manager = business
    with psycopg.connect(pg_database.operator_url) as connection:
        # Paging needs enough projects within the default In Progress filter.
        connection.cursor().executemany("INSERT INTO eppm.project(id,name,status) VALUES(%s,%s,'In Progress')", [(index, f"Project {index}") for index in range(3, 303)])
    with patch("app.presentation.pages.portfolio.portfolio_project_table") as table:
        app = AppTest.from_function(portfolio_app, args=(path, manager.actor), default_timeout=30).run()
        assert not app.exception and not app.error
        context = table.call_args.kwargs["page_info"]["context"]
        app.session_state["portfolio_master_table"] = {"request": {
            "context": context, "kind": "page", "offset": 200, "query": {}, "nonce": "scroll-200",
        }}
        monkeypatch.setattr(service.policy, "clock", lambda: 1001)
        service.activity(manager.actor)
        app.run()
        assert not app.exception and not app.error
        info = table.call_args.kwargs["page_info"]
        assert info["context"] == context
        assert info["offset"] == 200 and info["request_id"] == "scroll-200"
        assert len(table.call_args.args[0]) == 100


def test_planning_reuses_chart_snapshot_after_activity(business, monkeypatch):
    from tests.business_ui import scoped_planning_app

    path, service, _, editor, _ = business
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as gantt:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
        assert not app.exception and not app.error
        token = app.session_state["planning_chart_snapshot"]["token"]
        assert "project_summaries" in gantt.call_args.kwargs
        monkeypatch.setattr(service.policy, "clock", lambda: 1001)
        service.activity(editor.actor)
        app.run()
        assert not app.exception and not app.error
        assert app.session_state["planning_chart_snapshot"]["token"] == token
        assert "project_summaries" not in gantt.call_args.kwargs
