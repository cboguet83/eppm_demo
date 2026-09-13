"""Statistics refreshes must not couple activity on independent browser sessions."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier, Lock

import psycopg
import pytest

from app.infrastructure.postgresql.access import PostgresAccessStore
from app.infrastructure.postgresql.migration import check_schema, discover_migrations, migrate
from tests.postgresql.test_access_service import administrator, identity, pg_access


def _predicate_footprint(connection: psycopg.Connection) -> set[tuple[str, str]]:
    """Inspect only this transaction's lock kinds and relation names."""
    return set(connection.execute(
        "SELECT DISTINCT locktype,relation::regclass::text FROM pg_locks "
        "WHERE pid=pg_backend_pid() AND mode='SIReadLock'").fetchall())


@pytest.mark.parametrize('analyzed', [False, True])
@pytest.mark.parametrize('population', [2, 50])
def test_independent_activity_uses_point_predicates_and_commits_without_false_retries(
    pg_database, pg_access, monkeypatch, record_property, analyzed, population,
):
    service = pg_access.service
    admin = administrator(pg_access)
    actors = [service.actor(service.sign_in(identity('independent-' + str(index)))) for index in range(population)]
    for actor in actors:
        service.set_status(admin, actor.user_id, 'active')
        service.grant(admin, actor.user_id, 'project_viewer', {'kind': 'all'})
    if analyzed:
        with psycopg.connect(pg_database.operator_url) as connection:
            for table in ('app_session', 'app_user', 'app_role_assignment'):
                connection.execute('ANALYZE eppm.' + table)
    pg_access.now[0] += 1
    ready = Barrier(2)
    lock = Lock()
    attempts = Counter()
    footprints = []
    original = PostgresAccessStore.record_activity

    def record(store, actor, now, expires_at):
        with lock:
            attempts[actor.user_id] += 1
            first = attempts[actor.user_id] == 1
        if first:
            footprint = _predicate_footprint(store.connection)
            with lock:
                footprints.append(footprint)
            ready.wait(timeout=10)
        planner = store.connection.execute('SHOW enable_seqscan').fetchone()
        result = original(store, actor, now, expires_at)
        assert store.connection.execute('SHOW enable_seqscan').fetchone() == planner
        footprint = _predicate_footprint(store.connection)
        with lock:
            footprints.append(footprint)
        return result

    monkeypatch.setattr(PostgresAccessStore, 'record_activity', record)
    with ThreadPoolExecutor(max_workers=2) as workers:
        pending = [workers.submit(service.activity, actor) for actor in actors[:2]]
        for result in pending:
            result.result(timeout=20)
    record_property('activity_attempt_counts', json.dumps(sorted(attempts.values())))
    relation_predicates = sum(('relation', 'app_session') in footprint for footprint in footprints)
    record_property('session_relation_predicates', relation_predicates)
    assert sorted(attempts.values()) == [1, 1]
    assert relation_predicates == 0
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.app_session WHERE last_activity=1001 AND expires_at=1901').fetchone() == (2,)
        assert connection.execute('SELECT count(*) FROM eppm.app_session WHERE last_activity=1000').fetchone() == (population - 1,)


def test_session_plan_upgrade_preserves_function_authority_and_applied_history(empty_database, tmp_path):
    migrations = discover_migrations()
    for migration in migrations[:27]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    metadata = """SELECT oid::regprocedure::text,prosrc,proowner,prosecdef,provolatile,proacl::text FROM pg_proc
        WHERE oid IN ('eppm.bind_actor(text,text)'::regprocedure,'eppm.current_actor(boolean)'::regprocedure,
                      'eppm.session_activity()'::regprocedure) ORDER BY proname"""
    ledger = 'SELECT version,name,checksum FROM eppm.schema_migration ORDER BY version'
    with psycopg.connect(empty_database.operator_url) as connection:
        before_functions = connection.execute(metadata).fetchall()
        before_ledger = connection.execute(ledger).fetchall()
    assert migrate(empty_database.operator_url) == tuple(item.name for item in migrations[27:])
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute(metadata).fetchall() == before_functions
        assert connection.execute(ledger).fetchall()[:27] == before_ledger
    with psycopg.connect(empty_database.runtime_url) as connection:
        check_schema(connection)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute('ALTER FUNCTION eppm.bind_actor(text,text) RESET enable_seqscan')
