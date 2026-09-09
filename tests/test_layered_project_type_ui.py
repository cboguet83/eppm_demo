"""Streamlit workflows and startup compatibility for the migrated feature."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.main import create_project_type_service
from app.infrastructure.database.schema_init import init_db
from app.main import create_schema_service

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def french_host_locale():
    """Exercise widget callbacks when the test host and app use different locales."""
    from app.presentation.i18n import get_current_locale, set_current_locale

    previous = get_current_locale()
    set_current_locale("fr")
    yield
    set_current_locale(previous)


def project_types_app(db_path: str) -> None:
    """Host the new screen with dependencies constructed outside presentation."""
    import pandas as pd
    from app.main import create_project_type_service
    from app.presentation.pages.project_types import render_project_types
    from app.presentation.i18n import set_current_locale

    set_current_locale("en")
    render_project_types(
        create_project_type_service(db_path),
        pd.DataFrame(columns=["param_id", "option_value"]),
    )


def button(app: AppTest, label: str):
    """Find a user-visible button independently of its position in the screen."""
    return next(item for item in app.button if item.label == label)


def test_project_type_screen_create_rename_duplicate_and_delete(tmp_path: Path) -> None:
    """User actions reach the application service and preserve the General type."""
    path = str(tmp_path / "screen.db")
    init_db(path)
    service = create_project_type_service(path)
    app = AppTest.from_function(project_types_app, args=(path,), default_timeout=15).run()
    assert not app.exception
    assert button(app, "Delete unused template").disabled
    button(app, "Create template").click().run()
    assert "name is required" in app.error[0].value
    app.text_input[0].input("Rail")
    button(app, "Create template").click().run()
    assert not app.exception
    type_id = service.get_all_types()[1].id
    button(app, "Create template").click().run()
    assert "already exists" in app.error[0].value
    assert "UNIQUE" not in app.error[0].value
    app.selectbox(key="template_type").select(type_id).run()
    app.text_input[1].input("Road")
    button(app, "Save template").click().run()
    assert not app.exception
    assert service.get_all_types()[1].name == "Road"
    button(app, "Delete unused template").click().run()
    assert not app.exception
    assert [item.name for item in service.get_all_types()] == ["General"]


def test_project_type_screen_saves_required_overrides_and_explicit_defaults(
    tmp_path: Path, french_host_locale: None,
) -> None:
    """The migrated UI can enable, edit, and remove a template's default value."""
    path = str(tmp_path / "rules.db")
    init_db(path)
    create_schema_service(path).create_parameter("p", None, "Detail", "TEXT")
    service = create_project_type_service(path)
    app = AppTest.from_function(project_types_app, args=(path,), default_timeout=15).run()
    assert not app.exception
    app.selectbox(key="rule_1_p").select("required").run()
    app.checkbox(key="has_default_1_p").check().run()
    app.text_input(key="default_1_p").input("Prefill")
    button(app, "Save property rule").click().run()
    assert not app.exception
    rule = service.get_template(1)[0]
    assert rule["mandatory"] is True
    assert rule["default_value"] == "Prefill"
    app.selectbox(key="rule_1_p").select("inherit").run()
    app.checkbox(key="has_default_1_p").uncheck().run()
    button(app, "Save property rule").click().run()
    assert not app.exception
    assert service.get_template(1)[0]["mandatory"] is False
    assert service.get_template(1)[0]["has_default"] is False


@pytest.mark.parametrize("launcher", ["streamlit_app.py", "streamlit_app.py"])
def test_existing_and_new_cli_help_preserve_startup_arguments(launcher: str) -> None:
    """Both source launchers continue to expose the original seeding flags."""
    result = subprocess.run(
        [sys.executable, launcher, "--help"], cwd=ROOT,
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "--force-reseed" in result.stdout
    assert "--projects" in result.stdout


@pytest.mark.parametrize("launcher", ["streamlit_app.py", "streamlit_app.py"])
def test_both_streamlit_launchers_bootstrap_the_real_application(
    launcher: str, tmp_path: Path,
) -> None:
    """An isolated process tests actual startup without reusing test module state."""
    db_path = tmp_path / "startup.db"
    env = {**os.environ, "DB_NAME": str(db_path), "FORCE_RESEED": "false",
           "SEED_PROJECTS_COUNT": "0"}
    code = (
        "from streamlit.testing.v1 import AppTest; "
        f"app = AppTest.from_file({launcher!r}, default_timeout=30).run(); "
        "assert not app.exception, [error.message for error in app.exception]; "
        "assert app.sidebar.radio, 'Navigation did not render'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        capture_output=True, text=True, check=False, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert db_path.exists()
