"""Real session persistence exercised through HTTP and live WebSocket boundaries."""

import secrets
from threading import Event

import psycopg
import pytest
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.application.services.access import AccessService, AuthorizationPolicy, DeploymentAccessService, SessionLimits
from app.domain.access.models import VerifiedIdentity
from app.infrastructure.authentication.http import AuthenticationRoutes, SESSION_COOKIE
from app.infrastructure.authentication.middleware import BrowserSecurityMiddleware
from app.infrastructure.authentication.oidc import create_oidc_client
from app.infrastructure.postgresql.oidc_state import PostgresOidcState
from app.infrastructure.authentication.session_middleware import ApplicationSessionMiddleware, SESSION_HEADER
from app.infrastructure.postgresql.access import PostgresAccessGateway, PostgresDeploymentAccessGateway
from app.infrastructure.postgresql.authorization import configure_signing_key
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.runtime import RuntimeResources
from app.shared.config.authentication import AuthenticationConfig


@pytest.fixture
def transport(pg_database, database):
    """Use real sessions and a restricted shared pool; bootstrap separately."""
    key = secrets.token_bytes(32)
    configure_signing_key(pg_database.operator_url, key.hex())
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
    resources = RuntimeResources(database, key)
    now = [1000]
    settings = AuthenticationConfig("development", "http://localhost:8080/realms/eppm", "test-client",
                                    secrets.token_urlsafe(32), "http://localhost:8501",
                                    secrets.token_urlsafe(48), local_http=True)
    policy = AuthorizationPolicy(lambda: now[0], SessionLimits())
    access = AccessService(PostgresAccessGateway(database, key, policy), policy,
                           settings.issuer, lambda: secrets.token_urlsafe(32))
    cookie = access.sign_in(VerifiedIdentity(settings.issuer, "transport-admin", "", "Admin", 1000, 100000, True))
    actor = access.actor(cookie)
    DeploymentAccessService(PostgresDeploymentAccessGateway(OperatorDatabase(pg_database.operator_url)), lambda: now[0], "test", lambda: secrets.token_urlsafe(16)).bootstrap(actor.user_id)

    async def echo(websocket):
        await websocket.accept()
        await websocket.send_text(websocket.headers[SESSION_HEADER])
        try:
            while True:
                message = await websocket.receive_text()
                await websocket.send_text(message)
        except WebSocketDisconnect:
            return

    app = Starlette(routes=[WebSocketRoute("/_stcore/stream", echo)], middleware=[
        Middleware(BrowserSecurityMiddleware, config=settings),
        Middleware(ApplicationSessionMiddleware, access=access, config=settings),
    ])
    with TestClient(app, base_url=settings.origin) as browser:
        browser.cookies.set(SESSION_COOKIE, cookie)
        yield browser, access, actor, cookie, settings, now, resources


@pytest.mark.parametrize("change", ["logout", "idle", "permission"])
def test_live_messages_close_after_revocation_expiry_or_permission_change(pg_database, transport, change):
    browser, access, actor, cookie, settings, now, resources = transport
    identity, state, revision = access.browser_identity(cookie)
    with browser.websocket_connect("ws://localhost:8501/_stcore/stream", headers={"origin": settings.origin,
                                      SESSION_HEADER: "forged-owner", SESSION_HEADER.upper(): "second-forgery"}) as socket:
        assert socket.receive_text() == settings.session_binding(identity.session_hash, state, revision)
        socket.send_text("authorized interaction")
        assert socket.receive_text() == "authorized interaction"
        with psycopg.connect(pg_database.operator_url) as connection:
            assert connection.execute("SELECT last_activity FROM eppm.app_session").fetchone()[0] == 1000
        if change == "logout":
            access.logout(actor)
        elif change == "idle":
            now[0] = 1900
        else:
            access.grant(actor, actor.user_id, "business_admin", {"kind": "all"})
        socket.send_text("stale interaction")
        with pytest.raises(WebSocketDisconnect) as failure:
            socket.receive_text()
        assert failure.value.code == 1008


def test_other_browser_login_and_logout_do_not_disconnect_an_existing_page(pg_database, transport):
    browser, access, _, cookie, settings, _, resources = transport
    _, _, revision = access.browser_identity(cookie)
    with browser.websocket_connect("ws://localhost:8501/_stcore/stream", headers={"origin": settings.origin}) as socket:
        socket.receive_text()
        other_cookie = access.sign_in(VerifiedIdentity(settings.issuer, "other-browser", "", "Other", 1000, 100000, True))
        socket.send_text("still on the same page after another login")
        assert socket.receive_text() == "still on the same page after another login"
        access.logout(access.actor(other_cookie))
        socket.send_text("still on the same page after another logout")
        assert socket.receive_text() == "still on the same page after another logout"
    assert access.browser_identity(cookie)[2] == revision
    with psycopg.connect(pg_database.operator_url) as connection:
        actions = [row[0] for row in connection.execute("SELECT action FROM eppm.app_security_audit")]
    assert actions.count("authentication.success") == 2 and "session.logout" in actions


def test_anonymous_connection_cannot_forge_a_previous_runtime_owner(transport):
    browser, access, _, cookie, settings, _, _ = transport
    identity, state, revision = access.browser_identity(cookie)
    victim = settings.session_binding(identity.session_hash, state, revision)
    browser.cookies.clear()
    with browser.websocket_connect("ws://localhost:8501/_stcore/stream", headers={"origin": settings.origin, SESSION_HEADER: victim}) as socket:
        assert socket.receive_text() == settings.session_binding("anonymous", "anonymous", -1)


@pytest.mark.parametrize("change", ["logout", "idle", "revocation"])
def test_server_push_cannot_deliver_data_after_session_or_permission_changes(transport, change):
    _, access, actor, cookie, settings, now, _ = transport
    grant = access.grant(actor, actor.user_id, "business_admin", {"kind": "all"})
    release = Event()

    async def push(websocket):
        await websocket.accept()
        await websocket.send_text("ready")
        await run_in_threadpool(release.wait, 10)
        await websocket.send_text("protected background result")
        await websocket.send_text("duplicate after closure")

    app = Starlette(routes=[WebSocketRoute("/_stcore/stream", push)], middleware=[
        Middleware(BrowserSecurityMiddleware, config=settings),
        Middleware(ApplicationSessionMiddleware, access=access, config=settings),
    ])
    try:
        with TestClient(app, base_url=settings.origin) as browser:
            browser.cookies.set(SESSION_COOKIE, cookie)
            with browser.websocket_connect("ws://localhost:8501/_stcore/stream", headers={"origin": settings.origin}) as socket:
                assert socket.receive_text() == "ready"
                if change == "logout":
                    access.logout(actor)
                elif change == "idle":
                    now[0] = 1900
                else:
                    access.revoke(actor, grant)
                release.set()
                with pytest.raises(WebSocketDisconnect) as failure:
                    socket.receive_text()
                assert failure.value.code == 1008
    finally:
        release.set()


@pytest.mark.parametrize("origin", [None, "https://foreign.example.test"])
def test_logout_handler_independently_rejects_missing_or_foreign_origins(transport, origin):
    _, access, actor, cookie, settings, now, resources = transport
    client = create_oidc_client(settings, PostgresOidcState(resources.database, resources.key, lambda: now[0]))
    # Test the route's own defense even without the outer origin middleware.
    app = Starlette(routes=AuthenticationRoutes(client, access).routes(), middleware=[
        Middleware(SessionMiddleware, secret_key=settings.cookie_secret),
    ])
    with TestClient(app, base_url=settings.origin) as browser:
        browser.cookies.set(SESSION_COOKIE, cookie)
        response = browser.post("/auth/logout", headers={"origin": origin} if origin else {})
        assert response.status_code == 403 and response.headers["cache-control"] == "no-store"
        assert access.actor(cookie).user_id == actor.user_id


def test_expired_same_origin_logout_clears_cookie_and_audit_failure_is_safe_and_atomic(pg_database, transport, caplog):
    _, access, actor, cookie, settings, now, resources = transport
    client = create_oidc_client(settings, PostgresOidcState(resources.database, resources.key, lambda: now[0]))
    app = Starlette(routes=AuthenticationRoutes(client, access).routes(), middleware=[
        Middleware(SessionMiddleware, secret_key=settings.cookie_secret),
    ])
    with TestClient(app, base_url=settings.origin) as browser:
        browser.cookies.set(SESSION_COOKIE, cookie)
        with psycopg.connect(pg_database.operator_url) as connection:
            connection.execute("""CREATE FUNCTION eppm.reject_logout_audit() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN
                    RAISE EXCEPTION 'private storage diagnostics' USING ERRCODE='23514';
                END $$""")
            connection.execute("CREATE TRIGGER unavailable_logout_audit BEFORE INSERT ON eppm.app_security_audit "
                               "FOR EACH ROW EXECUTE FUNCTION eppm.reject_logout_audit()")
        failed = browser.post("/auth/logout", headers={"origin": settings.origin})
        assert failed.status_code == 503
        assert failed.headers["cache-control"] == "no-store"
        assert failed.json()["error"]["reference"]
        assert "private storage diagnostics" not in failed.text + caplog.text
        assert cookie not in failed.text + caplog.text
        assert access.actor(cookie).user_id == actor.user_id
        with psycopg.connect(pg_database.operator_url) as connection:
            connection.execute("DROP TRIGGER unavailable_logout_audit ON eppm.app_security_audit")
        now[0] = 1900
        expired = browser.post("/auth/logout", headers={"origin": settings.origin})
        assert expired.status_code == 204 and not expired.content
        assert "Max-Age=0" in expired.headers["set-cookie"]


def test_authorized_download_storage_failure_returns_no_data_or_internal_diagnostics(pg_database, transport, caplog):
    from app.application.services.business_access import BusinessAccess
    from app.infrastructure.authentication.downloads import DownloadRoutes
    from app.main import create_planning_service

    _, access, actor, cookie, settings, _, resources = transport
    access.grant(actor, actor.user_id, "project_viewer", {"kind": "all"})
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name) VALUES(1,'Authorized project')")
        connection.execute("ALTER TABLE eppm.project_task RENAME TO unavailable_project_task")

    def export(current_actor, project_id):
        service = create_planning_service(resources, access=BusinessAccess(current_actor, access.policy))
        return service.export_project_template(project_id)

    app = Starlette(routes=DownloadRoutes(access, export).routes())
    with TestClient(app, base_url=settings.origin) as browser:
        browser.cookies.set(SESSION_COOKIE, cookie)
        response = browser.get("/downloads/projects/1/template.csv")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["code"] == "download_failed"
    assert response.json()["error"]["reference"]
    assert all(value not in response.text + caplog.text for value in (cookie, "does not exist", "project_task"))


@pytest.mark.parametrize("endpoint,method", [
    ("/media/previously-authorized.csv", "get"),
    ("/_stcore/upload_file/other-session/file", "put"),
    ("/_stcore/upload_file/other-session/file", "delete"),
    ("/_stcore/metrics", "get"),
])
def test_native_data_routes_cannot_bypass_application_transport_policy(transport, endpoint, method):
    browser, _, _, _, settings, _, _ = transport
    response = getattr(browser, method)(endpoint, headers={"origin": settings.origin})
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
