"""Single-use authorization state on actual PostgreSQL worker transactions."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import get_ident

import psycopg
import pytest

from app.infrastructure.postgresql.oidc_state import PostgresOidcState


def test_state_preserves_opaque_text_hashes_keys_and_caps_lifetime(authorized):
    now = [1000]
    cache = PostgresOidcState(authorized.database, authorized.key, lambda: now[0])
    value = ' {"nonce":"été", "data": [1, 2], "duplicate":1,"duplicate":2} '
    asyncio.run(cache.set("browser-request", value, 3600))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT state_hash,data,expires_at FROM eppm.app_oidc_state").fetchone() == (
            sha256(b"browser-request").hexdigest(), value, 1600)
    now[0] = 1599
    assert asyncio.run(cache.get("browser-request")) == value
    assert asyncio.run(cache.get("browser-request")) is None
    asyncio.run(cache.delete("browser-request"))


@pytest.mark.parametrize("duration", [-1, 0, 1, 600])
def test_expired_state_is_consumed_without_returning_credentials(authorized, duration):
    now = [1000]
    cache = PostgresOidcState(authorized.database, authorized.key, lambda: now[0])
    asyncio.run(cache.set("request", "private verifier", duration))
    now[0] += max(duration, 0)
    assert asyncio.run(cache.get("request")) is None
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.app_oidc_state").fetchone() == (0,)


def test_store_prunes_expired_requests_and_delete_discards_valid_state(authorized):
    now = [1000]
    cache = PostgresOidcState(authorized.database, authorized.key, lambda: now[0])
    asyncio.run(cache.set("expired", "old", 1))
    now[0] = 1001
    asyncio.run(cache.set("current", "new", 600))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT data FROM eppm.app_oidc_state").fetchall() == [("new",)]
    asyncio.run(cache.delete("current"))
    assert asyncio.run(cache.get("current")) is None


def test_duplicate_state_never_overwrites_an_existing_verifier(authorized):
    cache = PostgresOidcState(authorized.database, authorized.key, lambda: 1000)
    asyncio.run(cache.set("request", "original", 600))
    with pytest.raises(psycopg.errors.UniqueViolation):
        asyncio.run(cache.set("request", "replacement", 600))
    assert asyncio.run(cache.get("request")) == "original"


def test_concurrent_consumers_return_the_verifier_to_exactly_one_worker(authorized):
    cache = PostgresOidcState(authorized.database, authorized.key, lambda: 1000)
    asyncio.run(cache.set("request", "single verifier", 600))
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: cache._consume("request"), range(2)))
    assert results.count("single verifier") == 1 and results.count(None) == 1


def test_async_state_operations_move_real_database_work_off_the_event_loop(authorized):
    workers = []

    class ObservedState(PostgresOidcState):
        def _set(self, key, value, expires):
            workers.append(get_ident())
            return super()._set(key, value, expires)

        def _consume(self, key):
            workers.append(get_ident())
            return super()._consume(key)

    cache = ObservedState(authorized.database, authorized.key, lambda: 1000)

    async def operation():
        event_loop = get_ident()
        await cache.set("request", "value", 600)
        assert await cache.get("request") == "value"
        await cache.delete("request")
        assert len(workers) == 3 and all(worker != event_loop for worker in workers)

    asyncio.run(operation())


def retry_state_once(authorized, event):
    """Force a definite native rollback, never replace persistence with a mock."""
    assert event in {"INSERT", "DELETE"}
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("CREATE SEQUENCE eppm.test_state_attempt")
        connection.execute("""CREATE FUNCTION eppm.retry_test_state() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF nextval('eppm.test_state_attempt')=1 THEN RAISE EXCEPTION 'Known rollback' USING ERRCODE='40001'; END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW; END $$""")
        connection.execute(psycopg.sql.SQL("CREATE TRIGGER retry_test_state BEFORE {} ON eppm.app_oidc_state FOR EACH ROW EXECUTE FUNCTION eppm.retry_test_state()").format(psycopg.sql.SQL(event)))


def test_consume_retry_rechecks_expiry_after_definite_rollback(authorized):
    cache = PostgresOidcState(authorized.database, authorized.key, lambda: 1000)
    asyncio.run(cache.set("request", "expires during retry", 1))
    retry_state_once(authorized, "DELETE")
    moments = iter([1000, 1002])
    cache.clock = lambda: next(moments)
    assert asyncio.run(cache.get("request")) is None
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT last_value FROM eppm.test_state_attempt").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM eppm.app_oidc_state").fetchone() == (0,)


def test_store_retry_preserves_original_expiry(authorized):
    retry_state_once(authorized, "INSERT")
    moments = iter([1000, 1000, 1002])
    cache = PostgresOidcState(authorized.database, authorized.key, lambda: next(moments))
    asyncio.run(cache.set("request", "original deadline", 600))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT expires_at FROM eppm.app_oidc_state").fetchone() == (1600,)
        assert connection.execute("SELECT last_value FROM eppm.test_state_attempt").fetchone() == (2,)
