"""Actual Authlib HTTP authentication with PostgreSQL state, accounts and sessions."""

from base64 import urlsafe_b64decode
from dataclasses import dataclass
import json
from secrets import token_bytes, token_urlsafe
from time import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import psycopg
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.application.services.access import AccessService, AuthorizationPolicy, SessionLimits, session_digest
from app.infrastructure.authentication.http import AuthenticationRoutes, OIDC_COOKIE, SESSION_COOKIE
from app.infrastructure.authentication.middleware import BrowserSecurityMiddleware
from app.infrastructure.postgresql.access import PostgresAccessGateway
from app.infrastructure.postgresql.authorization import configure_signing_key
from app.infrastructure.postgresql.oidc_state import PostgresOidcState
from app.shared.config.authentication import AuthenticationConfig
from tests.oidc_provider import oidc_provider
from tests.postgresql.conftest import PostgreSQLFixture


@dataclass
class HttpScenario:
    """Real local storage and browser; Any is the external provider's claims boundary."""

    setup: PostgreSQLFixture
    config: AuthenticationConfig
    access: AccessService
    now: list[int]
    provider: dict[str, Any]
    browser: TestClient

    def begin(self) -> dict[str, str]:
        """Follow the application's real authorization redirect parameters."""
        response = self.browser.get('/auth/login?nav=finance')
        assert response.status_code == 302
        params = parse_qs(urlsplit(response.headers['location']).query)
        self.provider['authorization'] = params
        assert params['code_challenge_method'] == ['S256']
        assert params['redirect_uri'] == [self.config.callback_url]
        return {'state': params['state'][0], 'code': 'test-code', 'iss': self.config.issuer}


@pytest.fixture
def pg_http(pg_database, database):
    key = token_bytes(32)
    configure_signing_key(pg_database.operator_url, key.hex())
    now = [int(time())]
    config = AuthenticationConfig('production', 'https://identity.example.test/realms/eppm',
                                  'eppm-test', token_urlsafe(32), 'https://eppm.example.test',
                                  token_urlsafe(48), mfa_acr_values=('2',))
    policy = AuthorizationPolicy(lambda: now[0], SessionLimits())
    access = AccessService(PostgresAccessGateway(database, key, policy), policy,
                           config.issuer, lambda: token_urlsafe(32))
    cache = PostgresOidcState(database, key, policy.clock)
    provider, state = oidc_provider(config, cache, now)
    app = Starlette(routes=AuthenticationRoutes(provider, access).routes(), middleware=[
        Middleware(BrowserSecurityMiddleware, config=config),
        Middleware(SessionMiddleware, secret_key=config.cookie_secret, session_cookie=OIDC_COOKIE,
                   max_age=600, same_site='lax', https_only=True),
    ])
    with TestClient(app, base_url=config.origin, follow_redirects=False) as browser:
        yield HttpScenario(pg_database, config, access, now, state, browser)


def test_native_oidc_login_stores_verified_profile_and_hashes_only_session_cookie(pg_http):
    params = pg_http.begin()
    cookie = pg_http.browser.cookies.get(OIDC_COOKIE)
    payload = urlsafe_b64decode(cookie.split('.')[0] + '==').decode()
    assert 'code_verifier' not in payload and 'nonce' not in payload
    response = pg_http.browser.get('/auth/callback', params=params)
    assert response.status_code == 303
    assert response.headers['location'] == pg_http.config.origin + '/?nav=finance'
    headers = response.headers.get_list('set-cookie')
    session_cookie = next(value for value in headers if value.startswith(SESSION_COOKIE + '='))
    assert all(attribute in session_cookie for attribute in ('Secure', 'HttpOnly', 'SameSite=lax'))
    raw_cookie = pg_http.browser.cookies.get(SESSION_COOKIE)
    actor = pg_http.access.actor(raw_cookie)
    assert pg_http.access.account(actor)['status'] == 'pending'
    with psycopg.connect(pg_http.setup.operator_url) as connection:
        assert connection.execute('SELECT subject FROM eppm.app_identity').fetchone() == ('verified-test-subject',)
        assert connection.execute('SELECT display_name FROM eppm.app_user').fetchone() == ('Fictional User',)
        assert connection.execute('SELECT session_hash FROM eppm.app_session').fetchone() == (session_digest(raw_cookie),)
        assert connection.execute('SELECT count(*) FROM eppm.app_role_assignment').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.app_oidc_state').fetchone() == (0,)
        assert connection.execute('SELECT action FROM eppm.app_security_audit').fetchall() == [('authentication.success',)]
    assert pg_http.provider['signed'] not in str(pg_http.browser.cookies)
    assert pg_http.browser.get('/auth/session').json() == {'status': 'pending'}


@pytest.mark.parametrize('claims', [
    {'iss': 'https://foreign.example.test'}, {'aud': 'another-client'}, {'azp': 'another-client'},
    {'exp': 1}, {'iat': 9999999999}, {'auth_time': None}, {'auth_time': True},
    {'auth_time': 9999999999}, {'sub': None}, {'nonce': None}, {'nonce': 'wrong'},
])
def test_invalid_provider_claims_cannot_create_native_accounts_or_sessions(pg_http, claims, caplog):
    params = pg_http.begin()
    pg_http.provider['claims'] = claims
    response = pg_http.browser.get('/auth/callback', params=params)
    assert response.status_code == 401
    assert set(response.json()['error']) == {'code', 'message', 'reference'}
    assert not pg_http.browser.cookies.get(SESSION_COOKIE)
    with psycopg.connect(pg_http.setup.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.app_user').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.app_session').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.app_oidc_state').fetchone() == (0,)
    assert pg_http.provider['signed'] not in caplog.text
    assert 'test-code' not in caplog.text


def test_foreign_browser_and_replayed_state_fail_before_external_exchange(pg_http):
    params = pg_http.begin()
    pg_http.browser.cookies.clear()
    assert pg_http.browser.get('/auth/callback', params=params).status_code == 401
    assert pg_http.provider['exchanges'] == 0
    params = pg_http.begin()
    state_cookie = pg_http.browser.cookies.get(OIDC_COOKIE)
    assert pg_http.browser.get('/auth/callback', params=params).status_code == 303
    pg_http.browser.cookies.clear()
    pg_http.browser.cookies.set(OIDC_COOKIE, state_cookie)
    assert pg_http.browser.get('/auth/callback', params=params).status_code == 401
    assert pg_http.provider['exchanges'] == 1


def test_native_state_expiry_rejects_callback_without_contacting_token_endpoint(pg_http):
    params = pg_http.begin()
    pg_http.now[0] += 600
    assert pg_http.browser.get('/auth/callback', params=params).status_code == 401
    assert pg_http.provider['exchanges'] == 0


def test_native_session_activity_and_logout_require_origin_and_preserve_authentication_time(pg_http):
    assert pg_http.browser.get('/auth/callback', params=pg_http.begin()).status_code == 303
    raw_cookie = pg_http.browser.cookies.get(SESSION_COOKIE)
    initial_time = pg_http.now[0]
    pg_http.now[0] += 100
    assert pg_http.browser.post('/auth/activity').status_code == 403
    headers = {'origin': pg_http.config.origin, 'x-eppm-activity': 'user-interaction'}
    assert pg_http.browser.post('/auth/activity', headers=headers).status_code == 204
    with psycopg.connect(pg_http.setup.operator_url) as connection:
        assert connection.execute('SELECT auth_time,last_activity FROM eppm.app_session').fetchone() == (initial_time, initial_time + 100)
        assert connection.execute('SELECT revision FROM eppm.app_security_state').fetchone() == (0,)
    assert pg_http.browser.post('/auth/logout').status_code == 403
    assert pg_http.browser.post('/auth/logout', headers=headers).status_code == 204
    assert not pg_http.browser.cookies.get(SESSION_COOKIE)
    pg_http.browser.cookies.set(SESSION_COOKIE, raw_cookie)
    assert pg_http.browser.get('/auth/session').status_code == 401
    with psycopg.connect(pg_http.setup.operator_url) as connection:
        assert connection.execute('SELECT revoked FROM eppm.app_session').fetchone() == (True,)
        assert connection.execute('SELECT action FROM eppm.app_security_audit ORDER BY id').fetchall() == [
            ('authentication.success',), ('session.logout',)]


def test_audit_failure_rolls_back_native_login_and_never_logs_provider_credentials(pg_http, caplog):
    with psycopg.connect(pg_http.setup.operator_url) as connection:
        connection.execute("CREATE FUNCTION eppm.fail_http_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private diagnostic' USING ERRCODE='23514'; END $$")
        connection.execute('CREATE TRIGGER fail_http_audit BEFORE INSERT ON eppm.app_security_audit FOR EACH ROW EXECUTE FUNCTION eppm.fail_http_audit()')
    response = pg_http.browser.get('/auth/callback', params=pg_http.begin())
    assert response.status_code == 401
    assert not pg_http.browser.cookies.get(SESSION_COOKIE)
    with psycopg.connect(pg_http.setup.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.app_user').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.app_session').fetchone() == (0,)
    assert 'private diagnostic' not in caplog.text
    assert pg_http.provider['signed'] not in caplog.text


@pytest.mark.parametrize('nonce', ['', None])
def test_corrupt_native_nonce_is_rejected_without_persisting_an_identity(pg_http, nonce):
    params = pg_http.begin()
    with psycopg.connect(pg_http.setup.operator_url) as connection:
        stored = json.loads(connection.execute('SELECT data FROM eppm.app_oidc_state').fetchone()[0])
        stored['data']['nonce'] = nonce
        connection.execute('UPDATE eppm.app_oidc_state SET data=%s', (psycopg.types.json.Jsonb(json.dumps(stored)),))
    assert pg_http.browser.get('/auth/callback', params=params).status_code == 401
    with psycopg.connect(pg_http.setup.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.app_user').fetchone() == (0,)
