"""Exercise real Authlib code exchange and signature validation at the HTTP boundary."""

import asyncio
from base64 import urlsafe_b64decode
from dataclasses import replace
import json
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from joserfc.jwk import RSAKey
import psycopg
from psycopg.types.json import Jsonb
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.application.services.access import AccessService, AuthorizationPolicy, SessionLimits
from app.infrastructure.authentication.http import AuthenticationRoutes, OIDC_COOKIE, SESSION_COOKIE
from app.infrastructure.authentication.middleware import BrowserSecurityMiddleware
from tests.oidc_provider import oidc_provider
from app.infrastructure.postgresql.oidc_state import PostgresOidcState
from app.infrastructure.postgresql.access import PostgresAccessGateway
from app.infrastructure.postgresql.authorization import configure_signing_key
from app.runtime import RuntimeResources
from app.shared.config.authentication import AuthenticationConfig


@pytest.fixture
def oidc(pg_database, database, request: pytest.FixtureRequest):
    """Mock only the remote provider's HTTP transport; JOSE, state and SQL remain real."""
    key = secrets.token_bytes(32)
    configure_signing_key(pg_database.operator_url, key.hex())
    path = RuntimeResources(database, key)
    now = [int(time.time())]
    production = getattr(request, "param", False)
    config = AuthenticationConfig(
        "production" if production else "development",
        "https://identity.example.test/realms/eppm" if production else "http://keycloak.localhost:8080/realms/eppm",
        "eppm-test", secrets.token_urlsafe(32),
        "https://eppm.example.test" if production else "http://localhost:8501",
        secrets.token_urlsafe(48), local_http=not production, mfa_acr_values=("2",),
    )
    policy = AuthorizationPolicy(lambda: now[0], SessionLimits())
    access = AccessService(PostgresAccessGateway(database, key, policy), policy,
                           config.issuer, lambda: secrets.token_urlsafe(32))
    provider, state = oidc_provider(config, PostgresOidcState(path.database, path.key, lambda: now[0]), now)
    routes = AuthenticationRoutes(provider, access)
    app = Starlette(routes=routes.routes(), middleware=[
        Middleware(BrowserSecurityMiddleware, config=config),
        Middleware(SessionMiddleware, secret_key=config.cookie_secret, session_cookie=OIDC_COOKIE,
                   max_age=600, same_site="lax", https_only=config.secure_cookies),
    ])
    with TestClient(app, base_url=config.origin, follow_redirects=False) as browser:
        yield path, config, access, state, browser, now, provider


def begin(oidc, query: str = 'next=https://untrusted.example.test') -> dict[str, str]:
    """Start the actual Authlib redirect and keep the returned browser-bound state."""
    _, config, _, state, browser, _, _ = oidc
    response = browser.get('/auth/login?' + query)
    assert response.status_code == 302, response.text
    params = parse_qs(urlsplit(response.headers["location"]).query)
    state["authorization"] = params
    assert params["response_type"] == ["code"]
    assert params["redirect_uri"] == [config.callback_url]
    assert params["code_challenge_method"] == ["S256"]
    assert params["max_age"] == ["0"]
    return {"state": params["state"][0], "code": "test-authorization-code", "iss": config.issuer}


def test_verified_oidc_login_creates_pending_account_without_tokens_in_cookies(pg_database, oidc):
    path, config, access, state, browser, _, _ = oidc
    params = begin(oidc)
    state_cookie = browser.cookies.get(OIDC_COOKIE)
    payload = urlsafe_b64decode(state_cookie.split(".")[0] + "==").decode()
    assert "code_verifier" not in payload and "nonce" not in payload
    response = browser.get("/auth/callback", params=params)
    assert response.status_code == 303
    assert response.headers["location"] == config.origin + "/"
    assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=lax" in response.headers["set-cookie"]
    cookie = browser.cookies.get(SESSION_COOKIE)
    actor = access.actor(cookie)
    assert access.account(actor)["status"] == "pending"
    with psycopg.connect(pg_database.operator_url) as conn:
        assert conn.execute("SELECT count(*) FROM eppm.app_role_assignment").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM eppm.app_oidc_state").fetchone()[0] == 0
        assert conn.execute("SELECT session_hash FROM eppm.app_session").fetchone()[0] != cookie
    assert state["signed"] not in str(browser.cookies)
    assert "userinfo" not in str(browser.cookies)
    assert browser.get("/auth/session").json() == {"status": "pending"}


@pytest.mark.parametrize("plain_userinfo", [False, True])
def test_token_response_without_id_token_never_substitutes_unverified_profile_claims(pg_database, oidc, plain_userinfo):
    path, _, _, state, browser, _, _ = oidc
    params = begin(oidc)
    state["omit_id_token"] = True
    state["plain_userinfo"] = plain_userinfo
    response = browser.get("/auth/callback", params=params)
    assert response.status_code == 401
    assert not browser.cookies.get(SESSION_COOKIE)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.app_user").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM eppm.app_session").fetchone()[0] == 0


def test_verified_id_token_overrides_unverified_profile_fields_in_token_response(pg_database, oidc):
    path, _, _, state, browser, _, _ = oidc
    params = begin(oidc)
    state["plain_userinfo"] = True
    state["userinfo_claims"] = {"sub": "different-subject", "name": "Unverified Profile"}
    assert browser.get("/auth/callback", params=params).status_code == 303
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT subject FROM eppm.app_identity").fetchone()[0] == "verified-test-subject"
        assert connection.execute("SELECT display_name FROM eppm.app_user").fetchone()[0] == "Fictional User"


@pytest.mark.parametrize("invalid", [
    {"iss": "https://wrong.example.test"}, {"aud": "different-client"},
    {"aud": ["different-client", "also-wrong"], "azp": "eppm-test"},
    {"azp": "different-client"}, {"aud": ["eppm-test", "second"], "azp": None},
    {"exp": 1}, {"iat": 9999999999}, {"auth_time": None}, {"auth_time": 9999999999},
    {"auth_time": 1.5}, {"auth_time": True}, {"iat": 1.5}, {"exp": 9999999999.5},
    {"sub": None}, {"nonce": "wrong-nonce"}, {"nonce": None},
    {"nonce": "wrong-nonce", "nonce_supported": False},
])
def test_invalid_identity_claims_cannot_create_an_application_account(pg_database, oidc, invalid, caplog):
    path, _, _, state, browser, _, _ = oidc
    params = begin(oidc)
    state["claims"] = invalid
    response = browser.get("/auth/callback", params=params)
    assert response.status_code == 401
    assert set(response.json()["error"]) == {"code", "message", "reference"}
    assert not browser.cookies.get(SESSION_COOKIE)
    with psycopg.connect(pg_database.operator_url) as conn:
        assert conn.execute("SELECT count(*) FROM eppm.app_user").fetchone()[0] == 0
    assert state["signed"] not in caplog.text
    assert "test-authorization-code" not in caplog.text


def test_bad_signature_rejected_and_new_key_id_refreshes_jwks(oidc):
    _, _, _, state, browser, _, provider = oidc
    params = begin(oidc)
    state["key"] = RSAKey.generate_key(2048, parameters={"kid": "initial"})
    assert browser.get("/auth/callback", params=params).status_code == 401
    params = begin(oidc)
    state["key"] = RSAKey.generate_key(2048, parameters={"kid": "rotated"})
    state["jwks"] = [state["key"].as_dict(private=False)]
    assert "jwks" in provider.server_metadata
    assert browser.get("/auth/callback", params=params).status_code == 303
    assert state["key_fetches"] == 2


@pytest.mark.parametrize("nonce", ["", None])
def test_corrupted_server_nonce_never_establishes_a_session(pg_database, oidc, nonce):
    path, _, _, _, browser, _, _ = oidc
    params = begin(oidc)
    with psycopg.connect(pg_database.operator_url) as connection:
        stored = json.loads(connection.execute("SELECT data FROM eppm.app_oidc_state").fetchone()[0])
        stored["data"]["nonce"] = nonce
        connection.execute("UPDATE eppm.app_oidc_state SET data=%s", (Jsonb(json.dumps(stored)),))
    assert browser.get("/auth/callback", params=params).status_code == 401
    assert not browser.cookies.get(SESSION_COOKIE)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.app_user").fetchone()[0] == 0


@pytest.mark.parametrize("oidc", [True], indirect=True)
def test_production_oidc_responses_apply_secure_cookie_and_browser_header_policy(oidc):
    _, _, _, _, browser, _, _ = oidc
    response = browser.get("/auth/callback", params=begin(oidc))
    assert response.status_code == 303
    session_cookie = next(value for value in response.headers.get_list("set-cookie") if value.startswith(SESSION_COOKIE + "="))
    assert "Secure" in session_cookie and "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie
    for result in (response, browser.get("/auth/session")):
        assert result.headers["Strict-Transport-Security"] == "max-age=31536000"
        assert result.headers["Cache-Control"] == "no-store"
        assert result.headers["Referrer-Policy"] == "no-referrer"
        assert result.headers["X-Content-Type-Options"] == "nosniff"
        assert result.headers["X-Frame-Options"] == "SAMEORIGIN"
        assert result.headers["Content-Security-Policy"] == "frame-ancestors 'self'; object-src 'none'; base-uri 'self'"


def test_missing_wrong_replayed_and_foreign_browser_state_fail_before_exchange(oidc):
    _, _, _, state, browser, _, _ = oidc
    params = begin(oidc)
    assert browser.get("/auth/callback", params={**params, "state": "wrong"}).status_code == 401
    params = begin(oidc)
    cookie = browser.cookies.get(OIDC_COOKIE)
    browser.cookies.clear()
    assert browser.get("/auth/callback", params=params).status_code == 401
    assert state["exchanges"] == 0
    # Authlib discards a failed request's state, including a foreign browser callback.
    params = begin(oidc)
    cookie = browser.cookies.get(OIDC_COOKIE)
    assert browser.get("/auth/callback", params=params).status_code == 303
    browser.cookies.clear()
    browser.cookies.set(OIDC_COOKIE, cookie)
    assert browser.get("/auth/callback", params=params).status_code == 401
    assert state["exchanges"] == 1


@pytest.mark.parametrize("change", [
    {"issuer": "https://another.example.test"}, {"jwks_uri": "http://untrusted.example.test/keys"},
    {"jwks_uri": None},
    {"code_challenge_methods_supported": ["plain"]}, {"response_types_supported": ["token"]},
    {"id_token_signing_alg_values_supported": ["none", "HS256"]},
])
def test_unsafe_discovery_fails_closed(oidc, change):
    _, _, _, state, browser, _, _ = oidc
    state["metadata"].update(change)
    assert browser.get("/auth/login").status_code == 503
    assert not browser.cookies.get(SESSION_COOKIE)


def test_callback_rejects_issuer_mixup_and_duplicate_parameters(oidc):
    _, _, _, state, browser, _, _ = oidc
    params = begin(oidc)
    assert browser.get("/auth/callback", params={**params, "iss": "https://wrong.example.test"}).status_code == 401
    assert state["exchanges"] == 0
    params = begin(oidc)
    assert browser.get("/auth/callback?" + urlencode(params) + "&state=second").status_code == 401
    assert state["exchanges"] == 0


def test_expired_state_and_concurrent_consumption_are_single_use(oidc):
    path, _, _, _, browser, now, _ = oidc
    params = begin(oidc)
    now[0] += 601
    assert browser.get("/auth/callback", params=params).status_code == 401
    cache = PostgresOidcState(path.database, path.key, lambda: now[0])

    async def concurrent():
        await cache.set("concurrent", json.dumps({"data": {"nonce": "test"}}), 600)
        return await asyncio.gather(cache.get("concurrent"), cache.get("concurrent"))

    assert sum(value is not None for value in asyncio.run(concurrent())) == 1


def test_activity_requires_origin_and_explicit_event_and_logout_revokes_other_tabs(pg_database, oidc):
    path, config, _, _, browser, now, _ = oidc
    assert browser.get("/auth/callback", params=begin(oidc)).status_code == 303
    cookie = browser.cookies.get(SESSION_COOKIE)
    now[0] += 100
    assert browser.post("/auth/activity").status_code == 403
    assert browser.post("/auth/activity", headers={"Origin": config.origin}).status_code == 403
    assert browser.post("/auth/activity", headers={"Origin": "https://foreign.example.test", "X-Eppm-Activity": "user-interaction"}).status_code == 403
    assert browser.get("/auth/session").status_code == 200
    with psycopg.connect(pg_database.operator_url) as conn:
        assert conn.execute("SELECT last_activity FROM eppm.app_session").fetchone()[0] == now[0] - 100
    assert browser.post("/auth/activity", headers={"Origin": config.origin, "X-Eppm-Activity": "user-interaction"}).status_code == 204
    assert browser.post("/auth/logout", headers={"Origin": config.origin}).status_code == 204
    browser.cookies.set(SESSION_COOKIE, cookie)
    assert browser.get("/auth/session").status_code == 401
    assert browser.post("/auth/activity", headers={"Origin": config.origin, "X-Eppm-Activity": "user-interaction"}).status_code == 403


def test_cross_origin_websocket_and_foreign_host_are_rejected(oidc):
    _, _, _, _, browser, _, _ = oidc
    assert browser.get("/auth/login", headers={"Host": "evil.example.test"}).status_code == 403
    with pytest.raises(WebSocketDisconnect) as error:
        with browser.websocket_connect("/_stcore/stream", headers={"Origin": "https://evil.example.test"}):
            pass
    assert error.value.code == 1008


@pytest.mark.parametrize("change", [
    {"issuer": "http://identity.example.test"}, {"origin": "http://localhost:8501/path"},
    {"issuer": "https://user:pass@identity.example.test"}, {"issuer": "https://identity.example.test?x=1"},
    {"origin": "http://localhost:8501/"}, {"local_http": True, "environment": "production"},
    {"algorithms": ("none",)}, {"algorithms": ("HS256",)}, {"algorithms": ()},
    {"client_secret": ""}, {"cookie_secret": ""}, {"idle_seconds": 0},
    {"idle_seconds": -1}, {"reauthentication_seconds": -1},
])
def test_invalid_deployment_configuration_has_no_anonymous_fallback(oidc, change):
    _, config, _, _, _, _, _ = oidc
    with pytest.raises(ValueError):
        replace(config, **change)


def test_environment_mapping_and_production_mfa_cookie_policy(oidc):
    _, config, _, _, _, _, _ = oidc
    values = {"APP_ENV": "production", "APP_ORIGIN": "https://eppm.example.test",
              "OIDC_ISSUER": "https://identity.example.test/realm", "OIDC_CLIENT_ID": config.client_id,
              "OIDC_CLIENT_SECRET": config.client_secret, "APP_COOKIE_SECRET": config.cookie_secret,
              "OIDC_MFA_ACR_VALUES": "2,urn:example:mfa"}
    production = AuthenticationConfig.from_environment(values)
    assert production.secure_cookies and production.mfa_acr_values == ("2", "urn:example:mfa")
    assert config.client_secret not in repr(production) and config.cookie_secret not in repr(production)
    with pytest.raises(ValueError):
        AuthenticationConfig.from_environment({**values, "OIDC_MFA_ACR_VALUES": ""})
    with pytest.raises(ValueError):
        AuthenticationConfig.from_environment({})
    with pytest.raises(ValueError):
        AuthenticationConfig.from_environment({**values, "SESSION_IDLE_SECONDS": "invalid"})
    with pytest.raises(ValueError):
        AuthenticationConfig.from_environment({**values, "OIDC_ALLOW_LOCAL_HTTP": "perhaps"})


def test_internal_planning_destination_survives_oidc_and_cookie_has_no_fixed_expiry(oidc):
    _,config,_,_,browser,_,_=oidc
    params=begin(oidc,'nav=planning&project_id=17&task_id=23&next=https://untrusted.example.test')
    response=browser.get('/auth/callback',params=params)
    assert response.headers['location']==config.origin+'/?nav=planning&project_id=17&task_id=23'
    cookie=next(value for value in response.headers.get_list('set-cookie') if value.startswith(SESSION_COOKIE+'='))
    assert 'Max-Age' not in cookie and 'expires=' not in cookie.lower()


def test_session_and_activity_storage_outages_are_retryable(oidc,monkeypatch):
    _,config,access,_,browser,_,_=oidc
    browser.get('/auth/callback',params=begin(oidc))
    def unavailable(*args,**kwargs):
        raise RuntimeError('private database detail')
    monkeypatch.setattr(access,'actor',unavailable)
    for response in [browser.get('/auth/session'),browser.post('/auth/activity',headers={'Origin':config.origin,'X-Eppm-Activity':'user-interaction'})]:
        assert response.status_code==503 and 'private' not in response.text
