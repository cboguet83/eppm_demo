"""Real Streamlit account and access-administration boundaries with PostgreSQL."""

import psycopg
import secrets
import time

import pytest
from streamlit.testing.v1 import AppTest

from app.domain.access.models import VerifiedIdentity
from app.infrastructure.postgresql.authorization import configure_signing_key
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.operator_services import create_deployment_access_service
from app.runtime import RuntimeResources
from app.security import create_access_service
from app.shared.config.authentication import AuthenticationConfig


def access_screen(path: RuntimeResources, settings: AuthenticationConfig, cookie: str, require_admin_mfa: bool = False) -> None:
    """Render the production gate and administration screen with injected test transport."""
    from app.presentation.components.authentication import account_gate
    from app.presentation.pages.access_management import render_access_management
    from app.security import create_access_service
    from dataclasses import replace

    service = create_access_service(path, settings)
    if require_admin_mfa:
        service.policy.limits = replace(service.policy.limits, require_admin_mfa=True)
    actor = account_gate(service, cookie)
    if actor is not None:
        render_access_management(service, actor)


@pytest.fixture
def access_ui(pg_database, database):
    key = secrets.token_bytes(32)
    configure_signing_key(pg_database.operator_url, key.hex())
    with psycopg.connect(pg_database.operator_url) as connection:
        ensure_reference_catalog(connection)
    path = RuntimeResources(database, key)
    settings = AuthenticationConfig("development", "http://keycloak.localhost:8080/realms/eppm", "eppm-test",
                                     secrets.token_urlsafe(32), "http://localhost:8501", secrets.token_urlsafe(48), local_http=True)
    service = create_access_service(path, settings)
    now = int(time.time())
    cookie = service.sign_in(VerifiedIdentity(settings.issuer, "verified-user", "user@example.test", "Example User",
                                              now, now + 3600, True))
    return path, settings, service, cookie


def test_anonymous_pending_and_disabled_screens_do_not_render_administration(access_ui, pg_database):
    path, settings, service, cookie = access_ui
    anonymous = AppTest.from_function(access_screen, args=(path, settings, "")).run()
    assert not anonymous.exception
    assert anonymous.title[0].value == "Sign in to EPPM"
    assert [item.key for item in anonymous.selectbox] == ["app_language_selector"]
    pending = AppTest.from_function(access_screen, args=(path, settings, cookie)).run()
    assert not pending.exception and "awaiting activation" in pending.info[0].value
    assert [item.key for item in pending.selectbox] == ["app_language_selector"]
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("UPDATE eppm.app_user SET status='disabled' WHERE id=%s", (service.actor(cookie).user_id,))
    pending.run()
    assert "disabled" in pending.info[0].value
    assert [item.key for item in pending.selectbox] == ["app_language_selector"]


def test_public_and_pending_accounts_can_choose_french_without_business_access(access_ui, pg_database):
    path, settings, service, cookie = access_ui
    anonymous = AppTest.from_function(access_screen, args=(path, settings, "")).run()
    anonymous.selectbox(key="app_language_selector").set_value("fr").run()
    assert not anonymous.exception and anonymous.title[0].value == "Connexion à EPPM"
    pending = AppTest.from_function(access_screen, args=(path, settings, cookie)).run()
    pending.selectbox(key="app_language_selector").set_value("fr").run()
    assert not pending.exception and "attend son activation" in pending.info[0].value
    assert not pending.header and not pending.button


def test_administration_ui_exposes_fixed_roles_and_keeps_bootstrap_out_of_browser(access_ui, pg_database):
    path, settings, service, cookie = access_ui
    user_id = service.actor(cookie).user_id
    operator = create_deployment_access_service(pg_database.operator_url)
    operator.bootstrap(user_id)
    app = AppTest.from_function(access_screen, args=(path, settings, cookie)).run()
    assert not app.exception
    assert app.header[0].value == "Application access"
    app.selectbox(key="access_selected_user").set_value(user_id).run()
    assert not app.exception
    assert set(app.selectbox(key="access_new_role").options) == {
        "Access administrator", "Business administrator", "Project viewer", "Project editor", "Project approver", "Finance editor",
    }
    assert all("bootstrap" not in button.label.lower() for button in app.button)
    app.selectbox(key="access_new_role").set_value("business_admin").run()
    app.button(key="access_grant").click().run()
    assert not app.exception
    assert {row["role"] for row in service.assignments(service.actor(cookie), user_id)} == {"access_admin", "business_admin"}
    app.button(key="access_revoke_1").click().run()
    assert not app.exception
    assert "At least one active access administrator" in app.error[0].value


def test_active_user_cannot_render_access_administration_without_access_role(access_ui, pg_database):
    path, settings, service, cookie = access_ui
    actor = service.actor(cookie)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("UPDATE eppm.app_user SET status='active' WHERE id=%s", (actor.user_id,))
    app = AppTest.from_function(access_screen, args=(path, settings, cookie)).run()
    assert not app.exception
    assert "not permitted" in app.error[0].value
    assert not app.selectbox


def test_administrator_can_retain_a_named_project_selection_and_grant_its_scope(access_ui, pg_database):
    import json

    path, settings, service, cookie = access_ui
    actor = service.actor(cookie)
    create_deployment_access_service(pg_database.operator_url).bootstrap(actor.user_id)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name) VALUES(1,'Visible project'),(2,'Other project')")
    target = service.register(actor, settings.issuer, "named-scope", "Scope User")
    service.set_status(actor, target, "active")
    app = AppTest.from_function(access_screen, args=(path, settings, cookie)).run()
    app.selectbox(key="access_selected_user").set_value(target).run()
    assert not app.exception and not app.error
    app.multiselect[0].set_value([1]).run()
    assert not app.exception and not app.error
    assert app.multiselect[0].value == [1]
    app.button(key="access_grant").click().run()
    assert not app.exception and not app.error
    assignments = service.assignments(actor, target)
    assert len(assignments) == 1 and assignments[0]["role"] == "project_viewer"
    assert json.loads(assignments[0]["scope_json"]) == {"kind": "projects", "project_ids": [1], "conditions": []}


@pytest.fixture
def french_locale():
    """AppTest also formats widget values outside the Streamlit script context."""
    from app.presentation.i18n import get_current_locale, set_current_locale

    previous = get_current_locale()
    set_current_locale("fr")
    try:
        yield
    finally:
        set_current_locale(previous)


def test_french_administration_explains_last_admin_and_empty_scope_errors(access_ui, pg_database, french_locale):
    path, settings, service, cookie = access_ui
    actor = service.actor(cookie)
    create_deployment_access_service(pg_database.operator_url).bootstrap(actor.user_id)
    app = AppTest.from_function(access_screen, args=(path, settings, cookie))
    app.session_state["locale"] = "fr"
    app.run()
    app.selectbox(key="access_selected_user").set_value(actor.user_id).run()
    assert app.header[0].value == "Accès à l'application"
    assert "Lecteur de projet" in app.selectbox(key="access_new_role").options
    app.button(key="access_revoke_1").click().run()
    assert not app.exception
    assert app.error[0].value == "Au moins un administrateur des accès actif doit être conservé."
    app.run()
    app.button(key="access_grant").click().run()
    assert not app.exception
    assert app.error[0].value == "Sélectionnez au moins une valeur de référence."


def test_administration_preregisters_exact_subject_and_activates_only_selected_account(access_ui, pg_database):
    path, settings, service, cookie = access_ui
    actor = service.actor(cookie)
    create_deployment_access_service(pg_database.operator_url).bootstrap(actor.user_id)
    app = AppTest.from_function(access_screen, args=(path, settings, cookie)).run()
    next(item for item in app.text_input if item.label == "Exact provider subject").set_value("external-subject-17")
    next(item for item in app.text_input if item.label == "Display name").set_value("Registered Account")
    next(item for item in app.button if item.label == "Create pending account").click().run()
    assert not app.exception and not app.error
    target = service.list_users(actor, "Registered Account")[0]
    assert target["status"] == "pending" and not service.assignments(actor, target["id"])
    with psycopg.connect(pg_database.operator_url) as connection:
        mapping = connection.execute("SELECT issuer,subject,verified_at FROM eppm.app_identity WHERE user_id=%s", (target["id"],)).fetchone()
        assert mapping == (settings.issuer, "external-subject-17", None)
    app.selectbox(key="access_selected_user").set_value(target["id"]).run()
    next(item for item in app.selectbox if item.label == "Account status").set_value("active")
    next(item for item in app.button if item.label == "Save account status").click().run()
    assert not app.exception and not app.error
    assert service.list_users(actor, "Registered Account")[0]["status"] == "active"
    assert service.account(actor)["status"] == "active"
    assert not service.assignments(actor, target["id"])


def test_property_scope_form_explains_and_matches_then_exposes_deleted_reference_for_repair(access_ui, pg_database):
    from app.domain.access.models import Permission

    path, settings, service, cookie = access_ui
    actor = service.actor(cookie)
    create_deployment_access_service(pg_database.operator_url).bootstrap(actor.user_id)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name) VALUES(1,'Matching project'),(2,'Without department')")
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES('DEPT','Department','ENUM')")
        connection.execute("INSERT INTO eppm.schema_param_options(id,param_id,option_value) VALUES(100,'DEPT','Finance')")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) VALUES(1,'DEPT','text','Finance')")
    target = service.register(actor, settings.issuer, "property-scope-user", "Property Scope User")
    service.set_status(actor, target, "active")
    department = next(item["property_id"] for item in service.scope_catalog(actor) if item.get("param_id") == "DEPT")
    app = AppTest.from_function(access_screen, args=(path, settings, cookie, True)).run()
    app.selectbox(key="access_selected_user").set_value(target).run()
    app.selectbox(key="access_new_role").set_value("project_approver").run()
    app.selectbox(key="access_scope_kind").set_value("properties").run()
    app.multiselect(key="access_scope_properties").set_value(["project_type_id", department]).run()
    app.multiselect(key="access_values_project_type_id").set_value([1]).run()
    app.selectbox(key=f"access_operator_{department}").set_value("in").run()
    app.multiselect(key=f"access_values_{department}").set_value([100]).run()
    app.button(key="access_grant").click().run()
    assert not app.exception and not app.error
    assignment = service.assignments(actor, target)[0]
    assert assignment["matching_projects"] == 1
    assert any("Department = Finance" in item.value and " and " in item.value for item in app.caption)
    explanation = service.effective_access(actor, target, 1)
    assert explanation[0]["permissions"] == [Permission.APPROVE, Permission.READ]
    next(item for item in app.button if item.label == "Check effective access").click().run()
    assert any(item.value.startswith(f'#{assignment["id"]} · Project approver:') for item in app.markdown)
    app.number_input(key="access_explain_project").set_value(2).run()
    next(item for item in app.button if item.label == "Check effective access").click().run()
    assert any("No assignment grants access" in item.value for item in app.info)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("DELETE FROM eppm.schema_param_options WHERE id=100")
    app.run()
    assert not app.exception and app.warning
    assert service.effective_access(actor, target, 1) == []
    app.button(key=f'access_revoke_{assignment["id"]}').click().run()
    assert not app.exception and not service.assignments(actor, target)
    app.selectbox(key="access_new_role").set_value("project_viewer").run()
    app.selectbox(key="access_scope_kind").set_value("all").run()
    app.button(key="access_grant").click().run()
    assert not app.exception and service.assignments(actor, target)[0]["matching_projects"] == 2
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("UPDATE eppm.app_role_assignment SET scope_json=%s::jsonb WHERE user_id=%s",
                           ('{"kind":"unsupported"}', target))
    app.run()
    assert not app.exception and app.warning
    assert any(item.value == "Invalid scope" for item in app.caption)
    app.selectbox(key="access_selected_user").set_value(actor.user_id).run()
    next(item for item in app.button if item.label == "Check effective access").click().run()
    assert not app.exception
    assert any("provider-verified MFA session" in item.value for item in app.caption)


def test_access_write_requires_reauthentication_without_changing_existing_grants(access_ui, pg_database):
    path, settings, service, cookie = access_ui
    actor = service.actor(cookie)
    create_deployment_access_service(pg_database.operator_url).bootstrap(actor.user_id)
    now = int(time.time())
    older_cookie = service.sign_in(VerifiedIdentity(settings.issuer, "verified-user", "user@example.test",
                                                     "Example User", now - 301, now + 3600, True), cookie)
    app = AppTest.from_function(access_screen, args=(path, settings, older_cookie)).run()
    app.selectbox(key="access_selected_user").set_value(actor.user_id).run()
    app.selectbox(key="access_new_role").set_value("business_admin").run()
    app.button(key="access_grant").click().run()
    assert not app.exception
    assert app.warning[0].value == "Sign in again before changing application access."
    assert app.get("link_button")[0].proto.url == "/auth/login"
    assert [grant["role"] for grant in service.assignments(service.actor(older_cookie), actor.user_id)] == ["access_admin"]
