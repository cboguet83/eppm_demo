"""Actual restricted pools are opened and closed only by the process lifecycle."""

import asyncio
from secrets import token_bytes
from threading import get_ident

import psycopg
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.infrastructure.postgresql.errors import DatabaseUnavailableError, SchemaCompatibilityError
from app.infrastructure.postgresql.pool import Database
from app.runtime import RuntimeResources
from app.shared.config.database import DatabaseConfig


def resources(setup):
    return RuntimeResources.from_environment({
        'DATABASE_URL': setup.runtime_url, 'DATABASE_CONTEXT_KEY': token_bytes(32).hex(),
        'DATABASE_POOL_MIN': '2', 'DATABASE_POOL_MAX': '3',
    })


def test_construction_is_closed_and_lifecycle_reuses_one_pool_without_seeding(pg_database):
    runtime = resources(pg_database)
    assert runtime.database.statistics().get('connections_num', 0) == 0
    with pytest.raises(DatabaseUnavailableError):
        runtime.database.run(lambda connection: connection.execute('SELECT 1').fetchone())

    async def health(_request):
        return JSONResponse({'identity': runtime.identity, 'size': runtime.database.statistics()['pool_size']})

    app = Starlette(routes=[Route('/health', health)], lifespan=runtime.lifespan)
    with TestClient(app) as client:
        first, second = client.get('/health').json(), client.get('/health').json()
        assert first == second == {'identity': runtime.identity, 'size': 2}
        assert runtime.database.run(lambda connection: connection.execute('SELECT 1').fetchone()) == (1,)
        with psycopg.connect(pg_database.operator_url) as connection:
            assert connection.execute('SELECT count(*) FROM eppm.project').fetchone() == (0,)
            assert connection.execute('SELECT count(*) FROM eppm.project_type').fetchone() == (0,)
            assert connection.execute('SELECT count(*) FROM eppm.app_user').fetchone() == (0,)
    with pytest.raises(DatabaseUnavailableError):
        runtime.database.run(lambda connection: connection.execute('SELECT 1').fetchone())


@pytest.mark.parametrize('failure', [False, True])
def test_lifecycle_opens_and_closes_in_worker_threads_even_when_application_fails(pg_database, failure):
    threads = {}
    class ObservedDatabase(Database):
        def open(self):
            threads['open'] = get_ident()
            super().open()
        def close(self):
            threads['close'] = get_ident()
            super().close()

    database = ObservedDatabase(DatabaseConfig(pg_database.runtime_url, pool_min=1, pool_max=2))
    runtime = RuntimeResources(database, token_bytes(32))
    async def run():
        threads['loop'] = get_ident()
        async with runtime.lifespan(None):
            assert database.statistics()['pool_size'] == 1
            if failure:
                raise RuntimeError('Synthetic application failure')
    if failure:
        with pytest.raises(RuntimeError, match='Synthetic application failure'):
            asyncio.run(run())
    else:
        asyncio.run(run())
    assert threads['open'] != threads['loop'] and threads['close'] != threads['loop']
    with pytest.raises(DatabaseUnavailableError):
        database.run(lambda connection: connection.execute('SELECT 1').fetchone())


def test_lifecycle_closes_after_cancellation(pg_database):
    runtime = resources(pg_database)
    async def run():
        async with runtime.lifespan(None):
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    with pytest.raises(DatabaseUnavailableError):
        runtime.database.run(lambda connection: connection.execute('SELECT 1').fetchone())


def test_startup_rejects_unmigrated_database_without_creating_schema(empty_database):
    runtime = resources(empty_database)
    async def run():
        async with runtime.lifespan(None):
            pytest.fail('An unmigrated database must not start.')
    with pytest.raises((DatabaseUnavailableError, SchemaCompatibilityError)):
        asyncio.run(run())
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM pg_namespace WHERE nspname='eppm'").fetchone() == (0,)


def test_runtime_resources_redact_credentials_and_do_not_fall_back_to_operator_settings():
    environment = {'DATABASE_URL': 'postgresql://app:private-password@localhost/example',
                   'DATABASE_CONTEXT_KEY': token_bytes(32).hex()}
    runtime = RuntimeResources.from_environment(environment)
    assert 'private-password' not in repr(runtime) and environment['DATABASE_CONTEXT_KEY'] not in repr(runtime)
    other = RuntimeResources.from_environment(environment)
    assert runtime.identity != other.identity and runtime.caches is not other.caches
    with pytest.raises(ValueError):
        RuntimeResources.from_environment({'DATABASE_OPERATOR_URL': environment['DATABASE_URL'],
                                           'DATABASE_CONTEXT_KEY': environment['DATABASE_CONTEXT_KEY']})
    for key in ('private-key', '', '11'):
        with pytest.raises(ValueError):
            RuntimeResources.from_environment(environment | {'DATABASE_CONTEXT_KEY': key})
    with pytest.raises(ValueError):
        RuntimeResources(runtime.database, b'invalid')
