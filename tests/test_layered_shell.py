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
from app.main import create_maintenance_service
from app.presentation.navigation import PAGE_PLANNING, PAGE_PORTFOLIO, PAGE_SETTINGS
from app.presentation.startup import bootstrap_database


def shell_app(database: str, force: bool = False) -> None:
    """Exercise shell behavior with real storage and a small route recorder."""
    from functools import partial
    import streamlit as st
    from app.main import create_maintenance_service
    from app.presentation.components.application_workspace import ApplicationWorkspace
    from app.presentation.navigation import PAGE_PLANNING, PAGE_PORTFOLIO, PAGE_SETTINGS
    from app.presentation.shell import render_application

    render_application(
        ApplicationWorkspace(
            database,
            "shell-test-v1",
            force,
            1,
            create_maintenance_service(database),
            {
                page: partial(st.write, page)
                for page in (PAGE_PLANNING, PAGE_PORTFOLIO, PAGE_SETTINGS)
            },
        )
    )


def application_app(database: str) -> None:
    """Render the actual composed pages against an isolated SQLite database."""
    from app.main import create_application_workspace
    from app.presentation.shell import render_application

    render_application(create_application_workspace(database))


@pytest.fixture
def database(tmp_path: Path):
    """Give each UI session an independent startup cache key and database."""
    bootstrap_database.clear()
    yield str(tmp_path / "shell.db")
    bootstrap_database.clear()


def test_sidebar_reseed_runs_once_and_preserves_edits_on_following_reruns(database):
    app = AppTest.from_function(shell_app, args=(database, True)).run()
    assert not app.exception
    assert create_maintenance_service(database).counts()["projects"] == 1
    app.number_input(key="sb_num_projects_input").set_value(2)
    app.button(key="btn_sidebar_force_reseed").click().run()
    assert not app.exception
    assert create_maintenance_service(database).counts()["projects"] == 2
    assert app.success and "2 projects" in app.success[0].value
    with closing(get_db(database)) as connection, connection:
        connection.execute("UPDATE project SET name = 'Preserved after reseed'")
    app.run()
    assert not app.exception
    assert not app.success
    with closing(get_db(database)) as connection:
        assert connection.execute("SELECT DISTINCT name FROM project").fetchall() == [
            ("Preserved after reseed",)
        ]


def test_shell_routes_navigation_redirects_and_language_changes(database):
    app = AppTest.from_function(shell_app, args=(database,)).run()
    assert not app.exception
    assert PAGE_PORTFOLIO in [item.value for item in app.markdown]
    app.radio(key="app_sidebar_nav").set_value(PAGE_SETTINGS).run()
    assert PAGE_SETTINGS in [item.value for item in app.markdown]
    app.session_state["nav_redirect"] = PAGE_PLANNING
    app.run()
    assert app.radio(key="app_sidebar_nav").value == PAGE_PLANNING
    app.selectbox(key="app_language_selector").set_value("fr").run()
    assert not app.exception
    assert app.selectbox(key="app_language_selector").value == "fr"
    app.session_state["nav_redirect"] = "obsolete route"
    app.run()
    assert PAGE_PORTFOLIO in [item.value for item in app.markdown]


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
    app = AppTest.from_function(application_app, args=(database,), default_timeout=30).run()
    assert not app.exception
    app.radio(key="app_sidebar_nav").set_value(PAGE_SETTINGS).run()
    assert app.radio(key="rb_settings_section").value == "org_structure"
    app.query_params.update(nav="schema")
    app.run()
    assert not app.exception
    assert app.radio(key="rb_settings_section").value == "param_def"


@pytest.mark.parametrize("operation", ["startup", "counts", "reseed"])
def test_shell_renders_safe_maintenance_errors_without_a_traceback(database, operation):
    app = AppTest.from_function(shell_app, args=(database,))
    if operation == "reseed":
        app.run()
        app.button(key="btn_sidebar_force_reseed").click()
    method = "startup" if operation == "reseed" else operation
    with patch(
        f"app.application.services.maintenance.MaintenanceService.{method}",
        side_effect=DatabaseMaintenanceError("Database operation could not be completed."),
    ):
        app.run()
    assert not app.exception
    assert app.error[0].value == "Database operation could not be completed."


def test_real_application_pages_run_without_importing_legacy_modules(tmp_path):
    """A fresh process catches indirect and dynamic legacy runtime dependencies."""
    database = str(tmp_path / "runtime.db")
    script = """
import sys
from streamlit.testing.v1 import AppTest
from app.presentation.navigation import PAGE_PLANNING, PAGE_SETTINGS

def render(database):
    from app.main import create_application_workspace
    from app.presentation.shell import render_application
    render_application(create_application_workspace(database))

app = AppTest.from_function(render, args=(sys.argv[1],), default_timeout=60).run()
assert not app.exception, list(app.exception)
for page in (PAGE_PLANNING, PAGE_SETTINGS):
    app.radio(key='app_sidebar_nav').set_value(page).run()
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


def test_historical_app_helpers_delegate_to_migrated_owners(database, monkeypatch):
    import app
    from app.shared.config import config

    monkeypatch.setattr(
        "app.compatibility.config",
        replace(
            config,
            db_path=database,
            force_reseed=False,
            seed_projects_count=0,
        ),
    )
    monkeypatch.setattr(sys, "argv", ["app.py"])
    assert app.bootstrap_database()
    groups, parameters, options = app.load_full_schema(database)
    assert len(groups) and len(parameters) and len(options)
    assert app.generate_param_id(database)
    assert app.get_next_available_group_order(database) > 0
    assert app._get_database_seed_counts(database)["projects"] == 5
    assert app._get_planning_totals(database)["pools"] == 103
    with pytest.raises(AttributeError):
        getattr(app, "unknown_export")


@pytest.mark.parametrize("argv", [["--help"], ["-h"]])
def test_compatibility_launcher_help_does_not_initialize_a_database(tmp_path, argv):
    import os

    database = tmp_path / "unopened.db"
    result = subprocess.run(
        [sys.executable, "app.py", *argv],
        env={**os.environ, "DB_NAME": str(database)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--force-reseed" in result.stdout and "--projects" in result.stdout
    assert not database.exists()


def test_cli_seed_count_uses_the_composed_maintenance_service(database, monkeypatch):
    from app.main import _run_cli
    from app.shared.config import config

    monkeypatch.setattr("app.shared.config.config", replace(config, db_path=database))
    monkeypatch.setattr(sys, "argv", ["app.py", "--projects", "2"])
    assert _run_cli()
    assert create_maintenance_service(database).counts()["projects"] == 2
    monkeypatch.setattr(sys, "argv", ["app.py"])
    assert not _run_cli()
    monkeypatch.setattr(sys, "argv", ["app.py", "--force"])
    with patch(
        "app.main.create_maintenance_service", side_effect=DatabaseMaintenanceError("Unavailable")
    ):
        with pytest.raises(SystemExit, match="1"):
            _run_cli()
