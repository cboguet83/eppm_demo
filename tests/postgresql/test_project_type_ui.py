"""Streamlit workflows and startup compatibility for the migrated feature."""

import os
import subprocess
import sys
from pathlib import Path
from secrets import token_hex

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from app.application.services.business_access import BusinessAccess
from app.main import create_project_type_service, create_schema_service
from app.runtime import RuntimeResources
from tests.postgresql.ui import runtime as runtime, access as access

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def french_host_locale():
    """Exercise widget callbacks when the test host and app use different locales."""
    from app.presentation.i18n import get_current_locale, set_current_locale

    previous = get_current_locale()
    set_current_locale("fr")
    yield
    set_current_locale(previous)


def project_types_app(runtime: RuntimeResources, access: BusinessAccess) -> None:
    """Host the new screen with dependencies constructed outside presentation."""
    import pandas as pd
    from app.main import create_project_type_service
    from app.presentation.pages.project_types import render_project_types
    from app.presentation.i18n import set_current_locale

    set_current_locale("en")
    render_project_types(
        create_project_type_service(runtime, access=access),
        pd.DataFrame(columns=["param_id", "option_value"]),
    )


def button(app: AppTest, label: str):
    """Find a user-visible button independently of its position in the screen."""
    return next(item for item in app.button if item.label == label)


def test_project_type_screen_create_rename_duplicate_and_delete(runtime: RuntimeResources, access: BusinessAccess) -> None:
    """User actions reach the application service and preserve the General type."""
    service = create_project_type_service(runtime, access=access)
    app = AppTest.from_function(project_types_app, args=(runtime, access), default_timeout=15).run()
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
    runtime: RuntimeResources, access: BusinessAccess, french_host_locale: None,
) -> None:
    """The migrated UI can enable, edit, and remove a template's default value."""
    create_schema_service(runtime, access=access).create_parameter("p", None, "Detail", "TEXT")
    service = create_project_type_service(runtime, access=access)
    app = AppTest.from_function(project_types_app, args=(runtime, access), default_timeout=15).run()
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


def test_source_launcher_cli_help_preserves_startup_arguments() -> None:
    """The supported source launcher exposes the original explicit seeding flags."""
    result = subprocess.run(
        [sys.executable, 'streamlit_app.py', "--help"], cwd=ROOT,
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "--force-reseed" in result.stdout
    assert "--projects" in result.stdout


def test_source_launcher_fails_closed_without_oidc_and_never_initializes_postgresql(empty_database) -> None:
    """An isolated process tests actual startup without reusing test module state."""
    env = {key: value for key, value in os.environ.items() if not key.startswith('OIDC_') and key not in {
        'DB_NAME', 'DATABASE_OPERATOR_URL', 'POSTGRES_TEST_ADMIN_URL', 'POSTGRES_PASSWORD', 'EPPM_RUNTIME_PASSWORD',
    }}
    env.update(DATABASE_URL=empty_database.runtime_url, DATABASE_CONTEXT_KEY=token_hex(32),
               FORCE_RESEED='false', SEED_PROJECTS_COUNT='0')
    code = (
        "from streamlit.testing.v1 import AppTest; "
        "app = AppTest.from_file('streamlit_app.py', default_timeout=30).run(); "
        "assert not app.exception, [error.message for error in app.exception]; "
        "assert not app.sidebar.radio; assert app.error"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        capture_output=True, text=True, check=False, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute("SELECT to_regnamespace('eppm')").fetchone() == (None,)
