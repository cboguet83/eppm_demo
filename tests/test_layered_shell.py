"""Storage-independent Streamlit routing and launcher contracts."""

import os
from pathlib import Path
import subprocess
import sys

import pytest
from streamlit.testing.v1 import AppTest

from app.presentation.navigation import PAGE_PLANNING, PAGE_PORTFOLIO, PAGE_SETTINGS


def shell_app() -> None:
    """Exercise shell routing with injected page renderers and totals."""
    from functools import partial
    import streamlit as st
    from app.presentation.components.application_workspace import ApplicationWorkspace
    from app.presentation.navigation import PAGE_PLANNING, PAGE_PORTFOLIO, PAGE_SETTINGS
    from app.presentation.shell import render_application

    st.session_state["shell_runs"] = st.session_state.get("shell_runs", 0) + 1

    def totals():
        st.session_state["totals_reads"] = st.session_state.get("totals_reads", 0) + 1
        return {"projects": 1, "tasks": 2, "dependencies": 0, "pools": 3}

    render_application(
        ApplicationWorkspace(
            'shell-routing-test',
            {
                page: partial(st.write, page)
                for page in (PAGE_PLANNING, PAGE_PORTFOLIO, PAGE_SETTINGS)
            },
            totals,
        )
    )



def test_shell_routes_navigation_redirects_and_language_changes():
    from tests.test_fragment_reruns import FragmentRun

    app = AppTest.from_function(shell_app)
    rerun = FragmentRun("app_sidebar_nav", widget_index=2, full_app_request=True)
    rerun.run(app)
    assert not app.exception
    assert PAGE_SETTINGS in [item.value for item in app.markdown]
    assert PAGE_PORTFOLIO not in [item.value for item in app.markdown]
    assert app.session_state["shell_runs"] == 1
    assert app.session_state["totals_reads"] == 1
    deltas = [message for message in rerun.messages if message.WhichOneof("type") == "delta"]
    assert deltas and all(message.metadata.delta_path[0] == 0 for message in deltas)
    assert all(message.delta.fragment_id for message in deltas)
    app.session_state["nav_redirect"] = PAGE_PLANNING
    app.run()
    assert app.radio(key="app_sidebar_nav").value == PAGE_PLANNING
    assert app.session_state["shell_runs"] == 2
    assert app.session_state["totals_reads"] == 2
    app.selectbox(key="app_language_selector").set_value("fr").run()
    assert not app.exception
    assert app.selectbox(key="app_language_selector").value == "fr"
    app.session_state["nav_redirect"] = "obsolete route"
    app.run()
    assert PAGE_PORTFOLIO in [item.value for item in app.markdown]



def test_retained_page_rejects_a_route_outside_the_authorized_workspace():
    def unavailable_page_app():
        import streamlit as st
        from app.presentation.components.application_workspace import ApplicationWorkspace
        from app.presentation.shell import _render_application_page

        st.session_state["app_sidebar_nav"] = "unavailable"
        _render_application_page(ApplicationWorkspace("unused", {"allowed": lambda: st.write("protected")}, None))

    app = AppTest.from_function(unavailable_page_app).run()
    assert not app.exception
    assert "no assigned application access" in app.info[0].value
    assert not app.markdown



@pytest.mark.parametrize("project_id,task_id", [("42", "7"), ("bad", "-2"), ("0", "")])
def test_planning_deep_links_validate_ids_and_consume_query_parameters(
    project_id, task_id
):
    app = AppTest.from_function(shell_app)
    app.query_params.update(nav="planning", project_id=project_id, task_id=task_id)
    app.run()
    assert not app.exception
    assert app.radio(key="app_sidebar_nav").value == PAGE_PLANNING
    assert not app.query_params
    if project_id == "42":
        assert app.session_state["target_planning_project_id"] == 42
        assert app.session_state["ms_multi_projects"] == [42]
        assert app.session_state["target_planning_task_id"] == 7
    else:
        assert "target_planning_project_id" not in app.session_state
        assert "target_planning_task_id" not in app.session_state



@pytest.mark.parametrize("argv", [["--help"], ["-h"]])
def test_launcher_help_does_not_initialize_a_database(argv):
    result = subprocess.run(
        [sys.executable, "streamlit_app.py", *argv],
        env={**os.environ, "DATABASE_URL": "unconfigured", "DATABASE_OPERATOR_URL": "unconfigured"},
        capture_output=True, text=True, check=False, timeout=30,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 0, result.stderr
    assert "--force-reseed" in result.stdout and "--projects" in result.stdout


@pytest.mark.parametrize("flag", ["--force", "-f", "--seed-projects", "-n"])
def test_retired_startup_flags_fail_without_initializing_storage(flag):
    result = subprocess.run(
        [sys.executable, "-m", "app.main", flag],
        env={**os.environ, "DATABASE_URL": "unconfigured", "DATABASE_OPERATOR_URL": "unconfigured"},
        capture_output=True, text=True, check=False, timeout=30,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def test_streamlit_main_ignores_operator_arguments_and_gates_unconfigured_business_access(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("DATABASE_URL", "unconfigured")
    monkeypatch.setattr(sys, "argv", ["streamlit_app.py", "--force-reseed", "--projects", "2"])
    monkeypatch.setattr("app.operator_services.create_maintenance_service",
                        lambda *args, **kwargs: pytest.fail("UI execution must not invoke maintenance."))

    def main_app():
        from app.main import main
        main()

    app = AppTest.from_function(main_app).run()
    assert not app.exception and app.error
    assert not app.radio and not app.dataframe and not app.metric
