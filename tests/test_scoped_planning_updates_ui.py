"""Gantt callbacks preserve scoped task and resource data while updating the chart."""

from contextlib import closing
import json
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.infrastructure.database.connection import get_db
from tests.test_business_transaction_security import business as business, scoped_planning_app


@pytest.mark.parametrize("action", ["update_dates", "update_progress"])
def test_inline_gantt_updates_refresh_only_authorized_tasks_and_pool_demand(business, action):
    path, _, _, editor, _ = business
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
        initial = component.call_args.kwargs
        assert [int(task["id"]) for task in initial["tasks"]] == [10]
        app.session_state["before_event"] = {
            "action": action, "id": 10, "start_date": "2026-02-02", "end_date": "2026-02-06",
            "progress": 40, "nonce": "inline-update",
        }
        app.run()
        assert not app.exception and not app.error
        delta = component.call_args.kwargs["patch"]
        assert delta["replace_projects"] == [1]
        assert [int(task["id"]) for task in delta["tasks"]] == [10]
        assert "Hidden" not in json.dumps(delta, default=str)
        assert ("resource_pools" in delta) == (action == "update_dates")
        if action == "update_dates":
            assert delta["resource_pools"]
        app.run()
        assert not app.exception and not app.error
    with closing(get_db(path)) as connection:
        visible = connection.execute("SELECT start_date,end_date,progress_pct FROM project_task WHERE id=10").fetchone()
        hidden = connection.execute("SELECT start_date,end_date,progress_pct FROM project_task WHERE id=20").fetchone()
        assert visible == (("2026-02-02", "2026-02-06", 0) if action == "update_dates" else ("2026-01-01", "2026-01-05", 40))
        assert hidden == ("2026-01-01", "2026-01-05", 0)
        assert connection.execute("SELECT id,fte_assigned FROM resource_pool_assignment ORDER BY id").fetchall() == [(1, 1), (2, 2)]


def test_lazy_gantt_hydration_discards_invalid_hidden_and_duplicate_project_ids(business):
    path, _, _, editor, _ = business
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
        app.session_state["before_event"] = {
            "action": "load_project_tasks", "project_ids": [[], "bad", 2, 999, 1, 1],
            "scope_token": component.call_args.kwargs["scope_token"], "nonce": "hydrate",
        }
        app.run()
        assert not app.exception and not app.error
        delta = component.call_args.kwargs["patch"]
        assert delta["replace_projects"] == [1]
        assert [int(task["id"]) for task in delta["tasks"]] == [10]
        assert "Hidden" not in json.dumps(delta, default=str)


@pytest.mark.parametrize("filter_scope", ["this", "all", "predecessors"])
def test_project_context_filter_callback_keeps_authorized_selection_through_full_rerun(business, filter_scope):
    path, _, _, editor, _ = business
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as component:
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
        app.session_state["before_event"] = {
            "action": "filter_project", "project_id": 1, "filter_scope": filter_scope, "nonce": "project-filter",
        }
        app.run()
        assert not app.exception and not app.error
        assert app.session_state["ms_multi_projects"] == [1]
        assert "Hidden" not in json.dumps(component.call_args.kwargs, default=str)
        assert "planning_needs_full_rerun" not in app.session_state


@pytest.mark.parametrize("event", [
    {"action": "update_dates", "id": 10, "start_date": "invalid", "end_date": "2026-02-06"},
    {"action": "update_dates", "id": 10, "start_date": "2026-02-06", "end_date": "2026-02-02"},
    {"action": "update_progress", "id": 10, "progress": None},
    {"action": "update_dates", "id": [], "start_date": "2026-02-02", "end_date": "2026-02-06"},
    {"action": "update_dates", "id": 20, "start_date": "2026-02-02", "end_date": "2026-02-06"},
])
def test_invalid_or_unauthorized_inline_updates_leave_tasks_and_allocations_unchanged(business, event):
    path, _, _, editor, _ = business
    with closing(get_db(path)) as connection:
        tasks = connection.execute("SELECT * FROM project_task ORDER BY id").fetchall()
        allocations = connection.execute("SELECT * FROM resource_pool_assignment ORDER BY id").fetchall()
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None):
        app = AppTest.from_function(scoped_planning_app, args=(path, editor.actor), default_timeout=30).run()
        app.session_state["before_event"] = event
        app.run()
        assert not app.exception
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT * FROM project_task ORDER BY id").fetchall() == tasks
        assert connection.execute("SELECT * FROM resource_pool_assignment ORDER BY id").fetchall() == allocations
