"""Actual native shell reruns, deep links and fresh-process page composition."""

import os
from pathlib import Path
import subprocess
import sys

import psycopg

from tests.postgresql.ui import access, native_screen, runtime


APPLICATION = """
from app.main import create_application_workspace
from app.presentation.shell import render_application
render_application(create_application_workspace(runtime, access=access))
"""


def test_shell_never_exposes_deployment_maintenance_or_reseeds_on_rerun(runtime, access, authorized):
    app = native_screen(APPLICATION, runtime, access).run()
    assert not app.exception
    assert not any("reseed" in str(button.key) for button in app.button)
    assert not any("seed" in str(item.key) for item in app.number_input)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='Preserved on rerun' WHERE id=1")
    app.run()
    assert not app.exception
    assert authorized.query("SELECT name FROM eppm.project WHERE id=1") == [("Preserved on rerun",)]
    assert authorized.query("SELECT count(*) FROM eppm.project", user_id=4) == [(3,)]


def test_schema_deep_link_selects_parameters_after_settings_was_already_open(runtime, access):
    from tests.test_fragment_reruns import FragmentRun

    app = native_screen(APPLICATION, runtime, access)
    FragmentRun("app_sidebar_nav", widget_index=3, full_app_request=True).run(app)
    assert not app.exception
    assert app.radio(key="rb_settings_section").value == "org_structure"
    app.query_params.update(nav="schema")
    app.run()
    assert not app.exception
    assert app.radio(key="rb_settings_section").value == "param_def"


def test_real_application_pages_run_without_importing_legacy_modules(runtime, authorized, tmp_path):
    """A fresh interpreter observes real page imports and restricted pool reads."""
    script_path = tmp_path / "native_shell_check.py"
    script_path.write_text(SMOKE_SOURCE, encoding="utf-8")
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("DATABASE_", "POSTGRES_TEST_"))
        and key != "EPPM_RUNTIME_PASSWORD"
    }
    environment.update(
        DATABASE_URL=authorized.setup.runtime_url,
        DATABASE_CONTEXT_KEY=authorized.key.hex(),
        DATABASE_POOL_MIN="1", DATABASE_POOL_MAX="2", PYTHONIOENCODING="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-c", "import runpy,sys; runpy.run_path(sys.argv[1])", str(script_path)],
        env=environment, capture_output=True, text=True, encoding="utf-8", check=False,
        cwd=Path(__file__).resolve().parents[2], timeout=120,
    )
    assert result.returncode == 0, result.stderr


SMOKE_SOURCE = """
import os
import sys
from streamlit.testing.v1 import AppTest
from app.application.services.access import AuthorizationPolicy, SessionLimits
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor
from app.runtime import RuntimeResources
from app.presentation.navigation import (
    PAGE_DASHBOARD, PAGE_PORTFOLIO, PAGE_PLANNING, PAGE_SETTINGS, PAGE_FINANCE,
)

runtime = RuntimeResources.from_environment(os.environ)
access = BusinessAccess(Actor(4, 'session-4', 'fresh-shell-request'), AuthorizationPolicy(lambda: 1000, SessionLimits()))
def render(resources, current_access):
    from app.main import create_application_workspace
    from app.presentation.shell import render_application
    render_application(create_application_workspace(resources, access=current_access))

runtime.database.open()
try:
    for page in (PAGE_DASHBOARD, PAGE_PORTFOLIO, PAGE_PLANNING, PAGE_SETTINGS, PAGE_FINANCE):
        app = AppTest.from_function(render, args=(runtime, access), default_timeout=30)
        app.session_state['app_sidebar_nav'] = page
        app.run()
        assert not app.exception, list(app.exception)
        assert app.radio(key='app_sidebar_nav').value == page
    forbidden = ('src', 'app.infrastructure.database', 'app.infrastructure.repositories',
                 'app.infrastructure.authentication.state')
    loaded = sorted(name for name in sys.modules
                    if any(name == prefix or name.startswith(prefix + '.') for prefix in forbidden))
    assert not loaded, loaded
finally:
    runtime.database.close()
"""
