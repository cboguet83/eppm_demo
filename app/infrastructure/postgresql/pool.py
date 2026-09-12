"""Process-owned pooled connections and complete, bounded transaction replay."""

from collections.abc import Callable
from contextlib import AbstractContextManager
import math
from time import sleep

import psycopg
from psycopg.errors import DeadlockDetected, SerializationFailure
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout

from app.infrastructure.postgresql.errors import (
    DatabaseUnavailableError, SchemaCompatibilityError, TransactionRetryError,
)
from app.infrastructure.postgresql.migration import check_schema
from app.shared.config.database import DatabaseConfig, validate_database_url


def run_transaction[Result](
    acquire: Callable[[], AbstractContextManager[psycopg.Connection]],
    operation: Callable[[psycopg.Connection], Result], *, write: bool = False,
    bind: Callable[[psycopg.Connection], None] | None = None,
) -> Result:
    """Replay a complete callback only after a definite concurrency rollback.

    Args:
        acquire: Explicit runtime-pool or separate operator connection source.
        operation: Replayable database work with no external side effects.
        write: Select serializable writes instead of a repeatable-read snapshot.
        bind: Reauthorize on each attempt before entering application code.
    """
    for attempt in range(3):
        try:
            with acquire() as connection:
                with connection.transaction():
                    connection.execute(
                        "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE READ WRITE" if write
                        else "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                    )
                    if bind is not None:
                        bind(connection)
                    return operation(connection)
        except (SerializationFailure, DeadlockDetected):
            if attempt == 2:
                raise TransactionRetryError("Concurrent changes prevented this operation. Please try again.") from None
            sleep(0.01 * (2 ** attempt))
        except (psycopg.OperationalError, psycopg.InterfaceError, PoolTimeout, PoolClosed):
            raise DatabaseUnavailableError("Database operation could not be completed. Please refresh.") from None
    raise AssertionError("Unreachable transaction retry state.")


class OperatorDatabase:
    """Explicit short-lived deployment connections, isolated from the runtime pool."""

    def __init__(self, url: str) -> None:
        """Require an operator URL explicitly; never fall back from runtime settings."""
        validate_database_url(url)
        self._url = url

    def _connection(self) -> psycopg.Connection:
        return psycopg.connect(self._url, autocommit=True, connect_timeout=5,
                               options="-c search_path=pg_catalog,eppm,pg_temp -c statement_timeout=10000",
                               application_name="eppm-operator")

    def run[Result](self, operation: Callable[[psycopg.Connection], Result], *, write: bool = False) -> Result:
        """Replay complete operator work with the same definite-rollback rules."""
        return run_transaction(self._connection, operation, write=write)


class Database:
    """An explicitly opened process resource, injected into repository gateways.

    Connections use autocommit outside explicit transactions. The callback
    interface alone owns business commits and can replay only known rollbacks.
    A lost connection, including during COMMIT, is never retried here.
    """

    def __init__(self, settings: DatabaseConfig) -> None:
        """Construct a closed pool without connecting or changing schema."""
        self._settings = settings
        self._pool = ConnectionPool(
            conninfo=settings.url,
            name="eppm-runtime",
            min_size=settings.pool_min,
            max_size=settings.pool_max,
            timeout=settings.acquire_timeout,
            open=False,
            kwargs={
                "autocommit": True,
                "connect_timeout": math.ceil(settings.acquire_timeout),
                "options": (
                    "-c search_path=pg_catalog,eppm,pg_temp "
                    f"-c statement_timeout={math.ceil(settings.statement_timeout * 1000)} "
                    "-c idle_in_transaction_session_timeout=30000"
                ),
                "application_name": "eppm-runtime",
            },
            reset=self._reset,
        )

    @staticmethod
    def _reset(connection: psycopg.Connection) -> None:
        # Transaction-local context already expired; also discard accidental
        # session-level changes before another actor borrows this connection.
        connection.execute("RESET ROLE")
        connection.execute("RESET ALL")
        connection.execute("DISCARD TEMP")

    def open(self) -> None:
        """Wait for minimum connections and reject privileged or incompatible runtime."""
        try:
            self._pool.open(wait=True, timeout=self._settings.acquire_timeout)
            with self._pool.connection() as connection:
                role = connection.execute("""
                    SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles r
                    WHERE (r.rolname = current_user OR pg_has_role(current_user, r.oid, 'SET'))
                      AND (r.rolsuper OR r.rolbypassrls OR r.rolcreatedb OR r.rolcreaterole
                        OR has_schema_privilege(r.oid, 'eppm', 'CREATE')
                        OR EXISTS (
                            SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                            WHERE n.nspname = 'eppm' AND c.relowner = r.oid
                        )))
                """).fetchone()
                if role is None or role[0]:
                    raise SchemaCompatibilityError("Application credentials must use a restricted runtime role.")
                check_schema(connection)
        except SchemaCompatibilityError:
            self.close()
            raise
        except (psycopg.Error, PoolTimeout, PoolClosed):
            self.close()
            raise DatabaseUnavailableError("Database is unavailable or not ready for this application.") from None

    def close(self) -> None:
        """Stop background workers and close this process's pooled connections."""
        self._pool.close()

    def statistics(self) -> dict[str, int]:
        """Return aggregate pool timings and counts, excluding actors and queries."""
        return self._pool.get_stats()

    def run[Result](
        self, operation: Callable[[psycopg.Connection], Result], *, write: bool = False,
        bind: Callable[[psycopg.Connection], None] | None = None,
    ) -> Result:
        """Commit a complete callback or retry its definite concurrency rollback.

        Args:
            operation: Replayable persistence callback with no external effects.
            write: Select serializable read-write instead of repeatable-read read-only.
            bind: Trusted actor/session binding, rerun before every callback attempt.
        """
        return run_transaction(self._pool.connection, operation, write=write, bind=bind)
