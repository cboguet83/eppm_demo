"""Display caches survive session activity but reauthorize every lookup."""

from contextlib import closing
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.domain.access.models import AccessDenied
from app.infrastructure.database.connection import get_db
from app.infrastructure.repositories.portfolio import SqlitePortfolioReader
from app.presentation.components.authorized_cache import authorized_cache
from tests.test_business_transaction_security import business as business


@pytest.mark.parametrize("journal_mode", ["DELETE", "WAL"])
def test_display_revision_is_stable_across_reads_and_session_activity(business, monkeypatch, journal_mode):
    path, service, _, editor, _ = business
    with closing(get_db(path)) as connection:
        connection.execute(f"PRAGMA journal_mode={journal_mode}")
    now = [1000]
    monkeypatch.setattr(service.policy, "clock", lambda: now[0])
    reader = SqlitePortfolioReader(path, access=editor)
    before = reader.revision()

    assert reader.revision() == before
    now[0] += 1
    service.activity(editor.actor)
    assert reader.revision() == before


@pytest.mark.parametrize("change", ["logout", "disabled", "revoked", "expired"])
def test_old_display_cache_keys_recheck_session_and_read_permission(business, monkeypatch, change):
    path, service, admin, editor, _ = business
    reader = SqlitePortfolioReader(path, access=editor)
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
    reader = SqlitePortfolioReader(path, access=manager)
    before = reader.revision()
    assignment = next(row["id"] for row in service.assignments(admin, admin.user_id) if row["role"] == "business_admin")

    service.revoke(admin, assignment)

    after = reader.revision()
    assert after[-1] == before[-1]
    assert after != before


@pytest.mark.parametrize("sql", [
    "UPDATE project SET name='Renamed' WHERE id=1",
    "UPDATE project_task SET end_date='2026-01-07' WHERE id=10",
    "UPDATE resource_pool_assignment SET fte_assigned=2 WHERE id=1",
    "UPDATE schema_parameters SET param_name='Renamed' WHERE param_id='DEPT'",
    "UPDATE project_property_value SET text_value='Delivery' WHERE project_id=1",
    "DELETE FROM task_dependencies",
    "INSERT INTO resource_pool_group(name) VALUES('New group')",
])
def test_display_revision_tracks_committed_business_changes_and_ignores_rollbacks(business, sql):
    path, _, _, editor, _ = business
    reader = SqlitePortfolioReader(path, access=editor)
    before = reader.revision()
    with closing(get_db(path)) as connection:
        connection.execute(sql)
        connection.rollback()
    assert reader.revision() == before

    with closing(get_db(path)) as connection, connection:
        connection.execute(sql)
    assert reader.revision() != before


def test_display_revision_ignores_derived_cache_writes(business):
    from app.infrastructure.database.planning_summary_cache import install_summary_cache

    path, _, _, editor, _ = business
    reader = SqlitePortfolioReader(path, access=editor)
    before = reader.revision()
    with closing(get_db(path)) as connection, connection:
        install_summary_cache(connection)
        connection.execute("INSERT INTO planning_summary_cache(project_id,name) VALUES(1,'Visible')")
        connection.execute("UPDATE pool_capacity_revision SET revision=revision+1")
    assert reader.revision() == before


def test_display_revision_upgrade_preserves_records_and_covers_business_sources(business):
    from app.infrastructure.database.display_revision import DISPLAY_SOURCE_TABLES
    from app.infrastructure.database.schema_init import init_db

    path, _, _, editor, _ = business
    with closing(get_db(path)) as connection, connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        excluded = {"schema_migration", "sqlite_sequence", "display_revision", "planning_summary_cache",
                    "pool_capacity_revision", "pool_capacity_cache", "pool_capacity_employee"}
        finance_tables = {"finance_snapshot", "finance_row", "finance_amount", "finance_cancellation"}
        assert tables - excluded - finance_tables - {name for name in tables if name.startswith("app_")} == DISPLAY_SOURCE_TABLES
        preserved = tables - excluded
        before = {name: connection.execute(f'SELECT * FROM "{name}" ORDER BY 1').fetchall() for name in preserved}
        triggers = connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'display_*'").fetchall()
        for name, in triggers:
            connection.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        connection.execute("DROP TABLE display_revision")

    init_db(path)
    reader = SqlitePortfolioReader(path, access=editor)
    epoch = reader.revision()[1]
    init_db(path)
    assert reader.revision()[1] == epoch
    with closing(get_db(path)) as connection:
        after = {name: connection.execute(f'SELECT * FROM "{name}" ORDER BY 1').fetchall() for name in preserved}
    assert after == before


@pytest.mark.parametrize("missing", ["row", "table"])
def test_missing_display_revision_fails_safely(business, missing):
    from app.application.exceptions import ProjectStorageError

    path, _, _, editor, _ = business
    with closing(get_db(path)) as connection, connection:
        connection.execute("DELETE FROM display_revision" if missing == "row" else "DROP TABLE display_revision")
    with pytest.raises(ProjectStorageError):
        SqlitePortfolioReader(path, access=editor).revision()


def test_portfolio_paging_keeps_context_and_requested_offset_after_activity(business, monkeypatch):
    from tests.test_fragment_reruns import portfolio_app

    path, service, _, _, manager = business
    with closing(get_db(path)) as connection, connection:
        connection.executemany("INSERT INTO project(id,name) VALUES(?,?)", [(index, f"Project {index}") for index in range(3, 303)])
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
