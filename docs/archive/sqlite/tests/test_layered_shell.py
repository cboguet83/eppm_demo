"""Real Streamlit startup, routing, and maintenance regression coverage."""

from contextlib import closing
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.application.exceptions import DatabaseMaintenanceError
from app.infrastructure.database.connection import get_db
from app.operator_services import create_maintenance_service
from app.presentation.navigation import PAGE_PLANNING, PAGE_PORTFOLIO, PAGE_SETTINGS


def shell_app(database: str) -> None:
    """Exercise shell behavior with real storage and a small route recorder."""
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
            database,
            {
                page: partial(st.write, page)
                for page in (PAGE_PLANNING, PAGE_PORTFOLIO, PAGE_SETTINGS)
            },
            totals,
        )
    )


def application_app(database: str) -> None:
    """Render the actual composed pages against an isolated SQLite database."""
    from app.operator_services import create_application_workspace
    from app.presentation.shell import render_application

    render_application(create_application_workspace(database))


@pytest.fixture
def database(tmp_path: Path):
    """Prepare isolated business data through the deployment-only service."""
    database = str(tmp_path / "shell.db")
    create_maintenance_service(database).startup(force=True, projects=1)
    return database


def test_shell_never_exposes_deployment_maintenance_or_reseeds_on_rerun(database):
    app = AppTest.from_function(shell_app, args=(database,)).run()
    assert not app.exception
    assert not any('reseed' in str(button.key) for button in app.button)
    assert not any('seed' in str(item.key) for item in app.number_input)
    with closing(get_db(database)) as connection, connection:
        connection.execute("UPDATE project SET name = 'Preserved on rerun'")
    app.run()
    assert not app.exception
    with closing(get_db(database)) as connection:
        assert connection.execute("SELECT DISTINCT name FROM project").fetchall() == [
            ("Preserved on rerun",)
        ]


def test_shell_routes_navigation_redirects_and_language_changes(database):
    from tests.test_fragment_reruns import FragmentRun

    app = AppTest.from_function(shell_app, args=(database,))
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
    database, project_id, task_id
):
    app = AppTest.from_function(shell_app, args=(database,))
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


def test_schema_deep_link_selects_parameters_after_settings_was_already_open(database):
    from tests.test_fragment_reruns import FragmentRun

    app = AppTest.from_function(application_app, args=(database,), default_timeout=30)
    FragmentRun("app_sidebar_nav", widget_index=3, full_app_request=True).run(app)
    assert not app.exception
    assert app.radio(key="rb_settings_section").value == "org_structure"
    app.query_params.update(nav="schema")
    app.run()
    assert not app.exception
    assert app.radio(key="rb_settings_section").value == "param_def"




def test_real_application_pages_run_without_importing_legacy_modules(tmp_path):
    """A fresh process catches indirect and dynamic legacy runtime dependencies."""
    database = str(tmp_path / "runtime.db")
    script = """
import sys
from streamlit.testing.v1 import AppTest
from app.presentation.navigation import PAGE_PLANNING, PAGE_SETTINGS
from app.operator_services import create_maintenance_service
create_maintenance_service(sys.argv[1]).startup(force=True, projects=1)

def render(database):
    from app.operator_services import create_application_workspace
    from app.presentation.shell import render_application
    render_application(create_application_workspace(database))

app = AppTest.from_function(render, args=(sys.argv[1],), default_timeout=60).run()
assert not app.exception, list(app.exception)
for page in (PAGE_PLANNING, PAGE_SETTINGS):
    app = AppTest.from_function(render, args=(sys.argv[1],), default_timeout=60)
    app.session_state['app_sidebar_nav'] = page
    app.run()
    assert not app.exception, list(app.exception)
assert not any(name == 'src' or name.startswith('src.') for name in sys.modules)
"""
    # AppTest needs a real source file to inspect the renderer's function body.
    script_path = tmp_path / "runtime_check.py"
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy,sys; sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0])",
            str(script_path),
            database,
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("argv", [["--help"], ["-h"]])
def test_launcher_help_does_not_initialize_a_database(tmp_path, argv):
    import os

    database = tmp_path / "unopened.db"
    result = subprocess.run(
        [sys.executable, "streamlit_app.py", *argv],
        env={**os.environ, "DB_NAME": str(database)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--force-reseed" in result.stdout and "--projects" in result.stdout
    assert not database.exists()


@pytest.mark.parametrize("flag", ["--force", "-f", "--seed-projects", "-n"])
def test_retired_startup_flags_fail_without_initializing_storage(tmp_path, flag):
    import os

    database = tmp_path / "unopened.db"
    result = subprocess.run(
        [sys.executable, "-m", "app.main", flag],
        env={**os.environ, "DB_NAME": str(database)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert not database.exists()


def test_cli_seed_count_uses_the_composed_maintenance_service(database, monkeypatch):
    from app.main import _run_cli, main
    from app.shared.config import config

    monkeypatch.setattr("app.shared.config.config", replace(config, db_path=database))
    monkeypatch.setattr(sys, "argv", ["streamlit_app.py", "--projects", "2"])
    main()
    assert create_maintenance_service(database).counts()["projects"] == 2
    monkeypatch.setattr(sys, "argv", ["streamlit_app.py"])
    assert not _run_cli()
    monkeypatch.setattr(sys, "argv", ["streamlit_app.py", "--force-reseed"])
    with patch(
        "app.operator_services.create_maintenance_service", side_effect=DatabaseMaintenanceError("Unavailable")
    ):
        with pytest.raises(SystemExit, match="1"):
            _run_cli()


def test_streamlit_main_ignores_operator_arguments_and_gates_unconfigured_business_access(tmp_path, monkeypatch):
    from app.shared.config import config

    database = tmp_path / "never-opened.db"
    monkeypatch.setattr("app.shared.config.config", replace(config, db_path=str(database)))
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setattr(sys, "argv", ["streamlit_app.py", "--force-reseed", "--projects", "2"])

    def main_app():
        from app.main import main
        main()

    app = AppTest.from_function(main_app).run()
    assert not app.exception and app.error
    assert not app.radio and not app.dataframe and not app.metric
    assert not database.exists()
