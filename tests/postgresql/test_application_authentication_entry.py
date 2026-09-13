"""Exercise the actual application entry point with isolated browser transport."""

from pathlib import Path
import secrets
import time

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from app.domain.access.models import VerifiedIdentity
from app.infrastructure.postgresql.authorization import configure_signing_key
from app.infrastructure.postgresql.migration import migrate
from app.operator_services import create_deployment_access_service
from app.runtime import RuntimeResources
from app.security import create_access_service
from app.shared.config.authentication import AuthenticationConfig
from scripts.configure_local_oidc import local_environment


def application_entry(cookie: str = "", binding: str = "") -> None:
    """Substitute browser transport only; execute real configuration, gates and pages."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.main import main
    from app.presentation.i18n import set_current_locale

    set_current_locale("en")
    transport = SimpleNamespace(
        cookies={"eppm_session": cookie},
        headers={"x-eppm-browser-session": binding},
    )
    with patch("streamlit.context", transport):
        main()


@pytest.fixture
def configured_entry(empty_database, monkeypatch):
    """Use generated in-memory test configuration, never deployment credentials."""
    environment = local_environment()
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    runtime = RuntimeResources.from_environment({
        'DATABASE_URL': empty_database.runtime_url,
        'DATABASE_CONTEXT_KEY': secrets.token_hex(32),
    })
    monkeypatch.setattr('app.runtime.process_runtime', lambda: runtime)
    try:
        yield empty_database, runtime, AuthenticationConfig.from_environment(environment)
    finally:
        runtime.database.close()


@pytest.mark.parametrize("configured", [False, True])
def test_public_startup_never_initializes_storage_or_routes_to_business_pages(
    configured_entry, monkeypatch, configured,
):
    setup, runtime, _ = configured_entry
    if not configured:
        monkeypatch.delenv("OIDC_CLIENT_ID")
    app = AppTest.from_function(application_entry, default_timeout=30)
    app.query_params.update(nav="settings", project_id="1")
    app.run()
    assert not app.exception and not app.radio and not app.dataframe
    if configured:
        assert app.title[0].value == "Sign in to EPPM"
    else:
        assert "not configured" in app.error[0].value
    app.run()
    assert not app.exception
    assert runtime.database.statistics().get('connections_num', 0) == 0
    with psycopg.connect(setup.operator_url) as connection:
        assert connection.execute("SELECT to_regnamespace('eppm')").fetchone() == (None,)


def active_browser(setup, runtime: RuntimeResources, settings: AuthenticationConfig):
    """Create a verified active account through isolated persistence fixtures."""
    migrate(setup.operator_url)
    configure_signing_key(setup.operator_url, runtime.key.hex())
    runtime.database.open()
    service = create_access_service(runtime, settings)
    now = int(time.time())
    cookie = service.sign_in(VerifiedIdentity(
        settings.issuer, "entry-subject", "entry@example.test", "Entry User",
        now, now + 3600, True,
    ))
    actor = service.actor(cookie)
    with psycopg.connect(setup.operator_url) as connection:
        connection.execute("UPDATE eppm.app_user SET status='active' WHERE id=%s", (actor.user_id,))
    return service, cookie, actor


@pytest.mark.parametrize("binding", ["", "untrusted-browser-value"])
def test_valid_cookie_cannot_bypass_the_application_transport_binding(configured_entry, binding):
    setup, runtime, settings = configured_entry
    _, cookie, _ = active_browser(setup, runtime, settings)
    app = AppTest.from_function(application_entry, args=(cookie, binding), default_timeout=30).run()
    assert not app.exception and not app.radio and not app.dataframe
    assert len(app.error) == 1 and "ASGI authentication launcher" in app.error[0].value


def test_security_revision_change_requires_a_fresh_runtime_before_admin_rendering(configured_entry):
    setup, runtime, settings = configured_entry
    service, cookie, actor = active_browser(setup, runtime, settings)
    current, status, revision = service.browser_identity(cookie)
    binding = settings.session_binding(current.session_hash, status, revision)
    app = AppTest.from_function(application_entry, args=(cookie, binding), default_timeout=30).run()
    assert not app.exception and not app.error
    assert app.radio(key="app_sidebar_nav").options == ["Dashboard", "Finance"]
    assert not app.header
    assert app.expander[0].label == "0 matching projects"

    create_deployment_access_service(setup.operator_url).bootstrap(actor.user_id)
    app.run()
    assert not app.exception and not app.radio
    assert "ASGI authentication launcher" in app.error[0].value

    current, status, revision = service.browser_identity(cookie)
    binding = settings.session_binding(current.session_hash, status, revision)
    from app.presentation.navigation import PAGE_ACCESS
    refreshed = AppTest.from_function(application_entry, args=(cookie, binding), default_timeout=30)
    refreshed.query_params["nav"] = PAGE_ACCESS
    refreshed.run()
    assert not refreshed.exception and not refreshed.error
    assert refreshed.radio(key="app_sidebar_nav").options == ["Dashboard", "Finance", "Application access"]
    assert refreshed.header[0].value == "Application access"


@pytest.mark.parametrize("with_traceback", [False, True])
def test_script_failure_records_code_location_without_payload_or_browser_details(
    configured_entry, monkeypatch, capsys, with_traceback,
):
    import importlib.util
    import logging
    import streamlit as st

    # The actual launcher configures logging. Preserve pytest's handlers across it.
    monkeypatch.setattr(logging.getLogger(), "handlers", [])
    launcher = Path(__file__).resolve().parents[2] / "asgi_app.py"
    specification = importlib.util.spec_from_file_location("isolated_asgi_error", launcher)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    rendered = []
    monkeypatch.setattr(st, "error", rendered.append)
    private_value = secrets.token_urlsafe(32)
    error = RuntimeError("Authorization: Bearer " + private_value + "\nforged log line")
    if with_traceback:
        try:
            raise error
        except RuntimeError as captured:
            assert module.script_error(captured)
    else:
        assert module.script_error(error)
    assert len(rendered) == 1 and "Reference:" in rendered[0]
    assert "RuntimeError" not in rendered[0] and private_value not in rendered[0]
    logged = capsys.readouterr().out
    assert "application.operation_failed" in logged and "exception=RuntimeError" in logged
    assert private_value not in logged and "forged log line" not in logged
    assert ("source=test_application_authentication_entry.py" if with_traceback else "source=unknown line=0") in logged
