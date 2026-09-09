"""Real session persistence exercised through HTTP and live WebSocket boundaries."""

from contextlib import closing
from pathlib import Path
import secrets

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.application.services.access import AccessService, AuthorizationPolicy, DeploymentAccessService, SessionLimits
from app.domain.access.models import VerifiedIdentity
from app.infrastructure.authentication.http import SESSION_COOKIE
from app.infrastructure.authentication.middleware import BrowserSecurityMiddleware
from app.infrastructure.authentication.session_middleware import ApplicationSessionMiddleware, SESSION_HEADER
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.schema_init import init_db
from app.infrastructure.repositories.access import SqliteAccessGateway
from app.presentation.components.csv_upload import MAX_CSV_BYTES, validated_csv_upload
from app.shared.config.authentication import AuthenticationConfig


@pytest.fixture
def transport(tmp_path: Path):
    path = str(tmp_path / "transport.db")
    init_db(path)
    now = [1000]
    settings = AuthenticationConfig("development", "http://localhost:8080/realms/eppm", "test-client",
                                    secrets.token_urlsafe(32), "http://localhost:8501",
                                    secrets.token_urlsafe(48), local_http=True)
    access = AccessService(SqliteAccessGateway(path), AuthorizationPolicy(lambda: now[0], SessionLimits()),
                           settings.issuer, lambda: secrets.token_urlsafe(32))
    cookie = access.sign_in(VerifiedIdentity(settings.issuer, "transport-admin", "", "Admin", 1000, 100000, True))
    actor = access.actor(cookie)
    DeploymentAccessService(access.gateway, lambda: now[0], "test", lambda: secrets.token_urlsafe(16)).bootstrap(actor.user_id)

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
        yield browser, access, actor, cookie, settings, now, path


@pytest.mark.parametrize("change", ["logout", "idle", "permission"])
def test_live_messages_close_after_revocation_expiry_or_permission_change(transport, change):
    browser, access, actor, cookie, settings, now, path = transport
    identity, state, revision = access.browser_identity(cookie)
    with browser.websocket_connect("ws://localhost:8501/_stcore/stream", headers={"origin": settings.origin,
                                      SESSION_HEADER: "forged-owner", SESSION_HEADER.upper(): "second-forgery"}) as socket:
        assert socket.receive_text() == settings.session_binding(identity.session_hash, state, revision)
        socket.send_text("authorized interaction")
        assert socket.receive_text() == "authorized interaction"
        with closing(get_db(path)) as connection:
            assert connection.execute("SELECT last_activity FROM app_session").fetchone()[0] == 1000
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


def test_anonymous_connection_cannot_forge_a_previous_runtime_owner(transport):
    browser, access, _, cookie, settings, _, _ = transport
    identity, state, revision = access.browser_identity(cookie)
    victim = settings.session_binding(identity.session_hash, state, revision)
    browser.cookies.clear()
    with browser.websocket_connect("ws://localhost:8501/_stcore/stream", headers={"origin": settings.origin, SESSION_HEADER: victim}) as socket:
        assert socket.receive_text() == settings.session_binding("anonymous", "anonymous", -1)


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


@pytest.mark.parametrize("payload", [
    "forged", {"error": "size"}, {"error": "encoding"}, {"content": 42, "name": "data.csv"},
    {"content": "data", "name": "not-csv.exe"}, {"content": "\x00", "name": "data.csv"},
    {"content": "x" * (MAX_CSV_BYTES + 1), "name": "data.csv"},
    {"content": "\u20ac" * (MAX_CSV_BYTES // 2), "name": "data.csv"},
    {"content": "\ud800", "name": "data.csv"},
    {"content": "data", "name": "x" * 256 + ".csv"},
])
def test_csv_component_rejects_malformed_or_oversized_payloads_on_server(payload):
    with pytest.raises(ValueError):
        validated_csv_upload(payload)


def test_csv_component_accepts_utf8_bom_and_empty_selection():
    assert validated_csv_upload(None) is None
    assert validated_csv_upload({"content": "\ufeffname\nExample", "name": "template.csv"}) == (
        "name\nExample", "template.csv",
    )
