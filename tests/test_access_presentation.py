"""Real Streamlit account and access-administration boundaries with real SQLite."""

from pathlib import Path
import secrets
import time

import pytest
from streamlit.testing.v1 import AppTest

from app.application.services.access import DeploymentAccessService
from app.domain.access.models import VerifiedIdentity
from app.infrastructure.database.schema_init import init_db
from app.infrastructure.repositories.access import SqliteAccessGateway
from app.security import create_access_service
from app.shared.config.authentication import AuthenticationConfig


def access_screen(path: str, settings: AuthenticationConfig, cookie: str) -> None:
    """Render the production gate and administration screen with injected test transport."""
    from app.presentation.components.authentication import account_gate
    from app.presentation.pages.access_management import render_access_management
    from app.security import create_access_service

    service = create_access_service(path, settings)
    actor = account_gate(service, cookie)
    if actor is not None:
        render_access_management(service, actor)


@pytest.fixture
def access_ui(tmp_path: Path):
    path = str(tmp_path / "access-ui.db")
    init_db(path)
    settings = AuthenticationConfig("development", "http://keycloak.localhost:8080/realms/eppm", "eppm-test",
                                     secrets.token_urlsafe(32), "http://localhost:8501", secrets.token_urlsafe(48), local_http=True)
    service = create_access_service(path, settings)
    now = int(time.time())
    cookie = service.sign_in(VerifiedIdentity(settings.issuer, "verified-user", "user@example.test", "Example User",
                                              now, now + 3600, True))
    return path, settings, service, cookie


def test_anonymous_pending_and_disabled_screens_do_not_render_administration(access_ui):
    path, settings, service, cookie = access_ui
    anonymous = AppTest.from_function(access_screen, args=(path, settings, "")).run()
    assert not anonymous.exception
    assert anonymous.title[0].value == "Sign in to EPPM"
    assert not anonymous.selectbox
    pending = AppTest.from_function(access_screen, args=(path, settings, cookie)).run()
    assert not pending.exception and "awaiting activation" in pending.info[0].value
    assert not pending.selectbox
    with service.gateway.transaction(write=True) as store:
        store.set_status(service.actor(cookie).user_id, "disabled", int(time.time()))
    pending.run()
    assert "disabled" in pending.info[0].value and not pending.selectbox


def test_administration_ui_exposes_fixed_roles_and_keeps_bootstrap_out_of_browser(access_ui):
    path, settings, service, cookie = access_ui
    user_id = service.actor(cookie).user_id
    operator = DeploymentAccessService(SqliteAccessGateway(path), lambda: int(time.time()), "ui-test", lambda: secrets.token_urlsafe(16))
    operator.bootstrap(user_id)
    app = AppTest.from_function(access_screen, args=(path, settings, cookie)).run()
    assert not app.exception
    assert app.header[0].value == "Application access"
    app.selectbox(key="access_selected_user").set_value(user_id).run()
    assert not app.exception
    assert set(app.selectbox(key="access_new_role").options) == {
        "access_admin", "business_admin", "project_viewer", "project_editor", "project_approver",
    }
    assert all("bootstrap" not in button.label.lower() for button in app.button)
    app.selectbox(key="access_new_role").set_value("business_admin").run()
    app.button(key="access_grant").click().run()
    assert not app.exception
    assert {row["role"] for row in service.assignments(service.actor(cookie), user_id)} == {"access_admin", "business_admin"}
    app.button(key="access_revoke_1").click().run()
    assert not app.exception
    assert "At least one active access administrator" in app.error[0].value


def test_active_user_cannot_render_access_administration_without_access_role(access_ui):
    path, settings, service, cookie = access_ui
    actor = service.actor(cookie)
    with service.gateway.transaction(write=True) as store:
        store.set_status(actor.user_id, "active", int(time.time()))
    app = AppTest.from_function(access_screen, args=(path, settings, cookie)).run()
    assert not app.exception
    assert "not permitted" in app.error[0].value
    assert not app.selectbox
