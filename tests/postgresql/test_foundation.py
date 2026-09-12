"""Migration atomicity, restricted pools, snapshot reads and whole-operation retry."""

from concurrent.futures import ThreadPoolExecutor
from secrets import token_urlsafe
from threading import Barrier, Event
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from app.infrastructure.postgresql.errors import (
    DatabaseUnavailableError, MigrationError, SchemaCompatibilityError, TransactionRetryError,
)
from app.infrastructure.postgresql.migration import (
    check_schema, discover_migrations, migrate,
)
from app.infrastructure.postgresql.pool import Database
from app.shared.config.database import DatabaseConfig, validate_database_url


@pytest.mark.parametrize("overrides", [
    {"pool_min": 0}, {"pool_max": 201}, {"pool_min": 3, "pool_max": 2},
    {"pool_min": True}, {"pool_max": 1.5}, {"acquire_timeout": 0},
    {"statement_timeout": float("inf")}, {"statement_timeout": float("nan")},
    {"statement_timeout": True}, {"acquire_timeout": 301},
])
def test_invalid_pool_settings_fail_before_connecting(overrides):
    with pytest.raises(ValueError):
        DatabaseConfig("postgresql://app:example@localhost/example", **overrides)


@pytest.mark.parametrize("url", ["", "sqlite:///example", "postgresql://localhost/db", "postgresql://app@host/",
                                     "postgresql://app@host:0/db", "postgresql://app@host:bad/db",
                                     "postgresql://app@host/db#fragment", "postgresql://app@host/db "])
def test_invalid_urls_are_not_exposed_in_errors(url):
    with pytest.raises(ValueError, match="Configure a valid PostgreSQL database URL"):
        validate_database_url(url)


def test_environment_validation_redacts_secrets_and_never_uses_operator_url():
    secret = "private-credential"
    settings = DatabaseConfig.from_environment({"DATABASE_URL": f"postgresql://app:{secret}@localhost/example"})
    assert (settings.pool_min, settings.pool_max, settings.acquire_timeout, settings.statement_timeout) == (2, 20, 5, 10)
    assert secret not in repr(settings)
    for environment in ({"DATABASE_OPERATOR_URL": settings.url},
                        {"DATABASE_URL": settings.url, "DATABASE_POOL_MAX": secret}):
        with pytest.raises(ValueError) as failure:
            DatabaseConfig.from_environment(environment)
        assert secret not in str(failure.value)


@pytest.mark.parametrize("filename,content", [
    ("invalid.sql", b"SELECT 1"), ("0002_gap.sql", b"SELECT 1"),
    ("0001_empty.sql", b"  "), ("0001_bad_encoding.sql", b"\xff"),
])
def test_migration_discovery_rejects_invalid_packages(tmp_path, filename, content):
    (tmp_path / filename).write_bytes(content)
    with pytest.raises(MigrationError):
        discover_migrations(tmp_path)


def test_migration_discovery_rejects_empty_packages_and_duplicate_versions(tmp_path):
    with pytest.raises(MigrationError, match="No migration"):
        discover_migrations(tmp_path)
    (tmp_path / "0001_first.sql").write_text("SELECT 1", encoding="utf-8")
    (tmp_path / "0001_duplicate.sql").write_text("SELECT 2", encoding="utf-8")
    with pytest.raises(MigrationError, match="unique"):
        discover_migrations(tmp_path)


def test_migrations_initialize_once_and_runtime_cannot_modify_the_ledger(pg_database, database):
    assert migrate(pg_database.operator_url) == ()
    database.run(check_schema)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        database.run(lambda connection: connection.execute("DELETE FROM eppm.schema_migration"), write=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        database.run(lambda connection: connection.execute("CREATE TABLE eppm.forbidden(id integer)"), write=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        database.run(lambda connection: connection.execute("CREATE TABLE public.forbidden(id integer)"), write=True)


def test_checksum_mismatch_and_future_schema_are_rejected(pg_database, tmp_path):
    for migration in discover_migrations():
        (tmp_path / migration.name).write_text(migration.sql + "\n-- changed", encoding="utf-8")
    with pytest.raises(SchemaCompatibilityError):
        migrate(pg_database.operator_url, directory=tmp_path)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.schema_migration VALUES (9999, 'future.sql', %s, now())", ("0" * 64,))
    with pytest.raises(SchemaCompatibilityError):
        migrate(pg_database.operator_url)


def test_failed_migrations_rollback_schema_and_all_prior_pending_files(empty_database, tmp_path):
    (tmp_path / "0001_probe.sql").write_text("CREATE TABLE eppm.probe(id integer)", encoding="utf-8")
    (tmp_path / "0002_failure.sql").write_text("SELECT missing_function()", encoding="utf-8")
    with pytest.raises(MigrationError, match="no changes"):
        migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute("SELECT to_regnamespace('eppm')").fetchone()[0] is None
    # Recovery applies the corrected package to the same database.
    assert migrate(empty_database.operator_url) == tuple(item.name for item in discover_migrations())


def test_competing_migration_runners_serialize_without_duplicate_ledger_entries(empty_database):
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: migrate(empty_database.operator_url), range(2)))
    assert sorted(map(len, results)) == [0, len(discover_migrations())]


def test_startup_rejects_owner(pg_database):
    owner = Database(DatabaseConfig(pg_database.operator_url, pool_min=1, pool_max=1))
    with pytest.raises(SchemaCompatibilityError, match="restricted"):
        owner.open()
    assert owner._pool.closed


def test_startup_rejects_privileges_available_only_through_set_role(pg_database):
    login, elevated = "eppm_login_" + uuid4().hex, "eppm_elevated_" + uuid4().hex
    password = token_urlsafe(36)
    with psycopg.connect(pg_database.operator_url, autocommit=True) as operator:
        operator.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(login), sql.Literal(password)))
        operator.execute(sql.SQL("CREATE ROLE {} NOLOGIN BYPASSRLS").format(sql.Identifier(elevated)))
        try:
            operator.execute(sql.SQL("GRANT eppm_runtime TO {}").format(sql.Identifier(login)))
            operator.execute(sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(sql.Identifier(elevated), sql.Identifier(login)))
            parsed = urlsplit(pg_database.runtime_url)
            url = urlunsplit(parsed._replace(netloc=f"{login}:{password}@{parsed.hostname}:{parsed.port}"))
            resource = Database(DatabaseConfig(url, pool_min=1, pool_max=1))
            with pytest.raises(SchemaCompatibilityError, match="restricted"):
                resource.open()
            assert resource._pool.closed
        finally:
            operator.execute(sql.SQL("DROP ROLE {}, {}").format(sql.Identifier(login), sql.Identifier(elevated)))


def test_startup_does_not_automigrate(empty_database):
    uninitialized = Database(DatabaseConfig(empty_database.runtime_url, pool_min=1, pool_max=1))
    with pytest.raises(DatabaseUnavailableError):
        uninitialized.open()
    assert uninitialized._pool.closed
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute("SELECT to_regnamespace('eppm')").fetchone()[0] is None


def test_missing_or_incompatible_schema_is_rejected_without_repair(pg_database):
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("DELETE FROM eppm.schema_migration")
    resource = Database(DatabaseConfig(pg_database.runtime_url, pool_min=1, pool_max=1))
    with pytest.raises(SchemaCompatibilityError):
        resource.open()
    assert resource._pool.closed
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("DROP TABLE eppm.schema_migration")
        with pytest.raises(SchemaCompatibilityError, match="operator migrations"):
            check_schema(connection)


def test_actor_context_clears_after_commit_and_rollback_on_reused_connection(pg_database):
    resource = Database(DatabaseConfig(pg_database.runtime_url, pool_min=1, pool_max=1))
    resource.open()
    try:
        def bind(connection):
            connection.execute("SELECT set_config('eppm.actor', 'first actor', true)")

        def read(connection):
            return connection.execute("SELECT pg_backend_pid(), current_setting('eppm.actor', true)").fetchone()

        first = resource.run(read, bind=bind)
        second = resource.run(read)
        assert first[0] == second[0] and first[1] == "first actor" and not second[1]

        def fail(connection):
            assert read(connection)[1] == "first actor"
            raise ValueError("domain validation")

        with pytest.raises(ValueError, match="domain validation"):
            resource.run(fail, write=True, bind=bind)
        assert not resource.run(read)[1]
    finally:
        resource.close()


def test_repeatable_read_sees_one_snapshot_and_is_read_only(probe, database):
    def operation(connection):
        first = connection.execute("SELECT value FROM eppm.transaction_probe WHERE id=1").fetchone()[0]
        with psycopg.connect(probe.operator_url) as writer:
            writer.execute("UPDATE eppm.transaction_probe SET value=1 WHERE id=1")
        second = connection.execute("SELECT value FROM eppm.transaction_probe WHERE id=1").fetchone()[0]
        return first, second

    assert database.run(operation) == (0, 0)
    assert database.run(lambda connection: connection.execute("SELECT value FROM eppm.transaction_probe WHERE id=1").fetchone()[0]) == 1
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        database.run(lambda connection: connection.execute("UPDATE eppm.transaction_probe SET value=2"))


def test_validation_failure_rolls_back_mutation_and_returns_connection(probe, database):
    def operation(connection):
        connection.execute("UPDATE eppm.transaction_probe SET value=100 WHERE id=1")
        raise ValueError("invalid command")

    with pytest.raises(ValueError, match="invalid command"):
        database.run(operation, write=True)
    assert database.run(lambda connection: connection.execute("SELECT value FROM eppm.transaction_probe WHERE id=1").fetchone()[0]) == 0


@pytest.mark.parametrize("sqlstate", ["40001", "40P01"])
def test_definite_rollback_replays_binding_and_whole_callback_without_duplicate_writes(probe, database, sqlstate):
    calls, bindings = [], []

    def bind(connection):
        bindings.append(connection.execute("SHOW transaction_isolation").fetchone()[0])

    def operation(connection):
        calls.append(connection.execute("SELECT value FROM eppm.transaction_probe WHERE id=1").fetchone()[0])
        connection.execute("UPDATE eppm.transaction_probe SET value=value+1 WHERE id=1")
        if len(calls) < 3:
            connection.execute(sql.SQL("DO $$ BEGIN RAISE EXCEPTION USING ERRCODE = {}; END $$").format(sql.Literal(sqlstate)))
        return "saved"

    assert database.run(operation, write=True, bind=bind) == "saved"
    assert calls == [0, 0, 0] and bindings == ["serializable"] * 3
    assert database.run(lambda connection: connection.execute("SELECT value FROM eppm.transaction_probe WHERE id=1").fetchone()[0]) == 1


def test_exhausted_retries_are_safe_and_rollback_every_attempt(probe, database):
    calls = []

    def operation(connection):
        calls.append(1)
        connection.execute("UPDATE eppm.transaction_probe SET value=value+1 WHERE id=1")
        connection.execute("DO $$ BEGIN RAISE EXCEPTION 'private SQL details' USING ERRCODE = '40001'; END $$")

    with pytest.raises(TransactionRetryError) as failure:
        database.run(operation, write=True)
    assert len(calls) == 3 and "private" not in str(failure.value)
    assert database.run(lambda connection: connection.execute("SELECT value FROM eppm.transaction_probe WHERE id=1").fetchone()[0]) == 0


@pytest.mark.parametrize("deadlock", [False, True])
def test_real_concurrent_writes_replay_the_losing_operation(probe, database, deadlock):
    barrier = Barrier(2)
    attempts = [0, 0]

    def save(index):
        def operation(connection):
            attempts[index] += 1
            if deadlock:
                ids = (1, 2) if index == 0 else (2, 1)
                connection.execute("UPDATE eppm.transaction_probe SET value=value+1 WHERE id=%s", (ids[0],))
                if attempts[index] == 1:
                    barrier.wait(timeout=10)
                connection.execute("UPDATE eppm.transaction_probe SET value=value+1 WHERE id=%s", (ids[1],))
            else:
                previous = connection.execute("SELECT value FROM eppm.transaction_probe WHERE id=1").fetchone()[0]
                if attempts[index] == 1:
                    barrier.wait(timeout=10)
                connection.execute("UPDATE eppm.transaction_probe SET value=%s WHERE id=1", (previous + 1,))
        database.run(operation, write=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(save, range(2)))
    assert sum(attempts) >= 3
    values = database.run(lambda connection: connection.execute("SELECT value FROM eppm.transaction_probe ORDER BY id").fetchall())
    assert values == ([(2,), (2,)] if deadlock else [(2,), (0,)])


def test_pool_exhaustion_is_bounded_and_recovers(pg_database):
    resource = Database(DatabaseConfig(pg_database.runtime_url, pool_min=1, pool_max=1, acquire_timeout=0.2))
    resource.open()
    entered, release = Event(), Event()

    def hold(connection):
        entered.set()
        assert release.wait(timeout=5)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(resource.run, hold)
            assert entered.wait(timeout=5)
            start = perf_counter()
            try:
                with pytest.raises(DatabaseUnavailableError):
                    resource.run(lambda connection: None)
                assert perf_counter() - start < 1.5
            finally:
                release.set()
            future.result(timeout=5)
        assert resource.run(lambda connection: connection.execute("SELECT 1").fetchone()[0]) == 1
        assert resource.statistics()["requests_errors"] >= 1
    finally:
        resource.close()


def test_connection_loss_before_commit_is_not_replayed(probe, database):
    calls = []

    def operation(connection):
        calls.append(1)
        connection.execute("UPDATE eppm.transaction_probe SET value=100 WHERE id=1")
        pid = connection.execute("SELECT pg_backend_pid()").fetchone()[0]
        with psycopg.connect(probe.operator_url, autocommit=True) as operator:
            operator.execute("SELECT pg_terminate_backend(%s)", (pid,))
        return "must not escape failed commit"

    with pytest.raises(DatabaseUnavailableError):
        database.run(operation, write=True)
    assert calls == [1]
    assert database.run(lambda connection: connection.execute("SELECT value FROM eppm.transaction_probe WHERE id=1").fetchone()[0]) == 0


def test_unavailable_server_and_closed_pool_return_safe_failures():
    resource = Database(DatabaseConfig("postgresql://app:private-secret@127.0.0.1:1/unavailable", pool_min=1, pool_max=1, acquire_timeout=0.1))
    with pytest.raises(DatabaseUnavailableError) as failure:
        resource.open()
    assert "private-secret" not in str(failure.value) and resource._pool.closed
    with pytest.raises(DatabaseUnavailableError):
        resource.run(lambda connection: None)


def test_statement_timeout_aborts_without_replaying_the_operation(pg_database):
    resource = Database(DatabaseConfig(pg_database.runtime_url, pool_min=1, pool_max=1, statement_timeout=0.05))
    resource.open()
    calls = []

    def operation(connection):
        calls.append(1)
        connection.execute("SELECT pg_sleep(1)")

    try:
        with pytest.raises(DatabaseUnavailableError):
            resource.run(operation)
        assert calls == [1]
        assert resource.run(lambda connection: connection.execute("SELECT 1").fetchone()[0]) == 1
    finally:
        resource.close()


def test_shutdown_closes_database_sessions(pg_database):
    resource = Database(DatabaseConfig(pg_database.runtime_url, pool_min=2, pool_max=2))
    resource.open()
    with psycopg.connect(pg_database.operator_url, autocommit=True) as operator:
        count_sql = "SELECT COUNT(*) FROM pg_stat_activity WHERE datname=current_database() AND application_name='eppm-runtime'"
        assert operator.execute(count_sql).fetchone()[0] == 2
        resource.close()
        assert operator.execute(count_sql).fetchone()[0] == 0
