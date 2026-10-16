"""Serialize benchmark namespace observers across test invocations."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.conninfo import make_conninfo

from tests.postgresql.template_database import (
    DatabaseFixtureError, PostgreSQLFixture,
)


BENCHMARK_LOCK = (1162887245, 1413829460)


@contextmanager
def benchmark_cluster_lock(database: PostgreSQLFixture) -> Iterator[None]:
    """Hold the test benchmark observation lock on the maintenance database.

    Args:
        database: Explicit isolated test-server operator coordinates.

    Yields:
        Exclusive access among cooperating benchmark test invocations.

    Raises:
        DatabaseFixtureError: Connection or bounded lock acquisition fails.
    """
    __tracebackhide__ = True
    try:
        with psycopg.connect(
            make_conninfo(database.operator_url, dbname="postgres"),
            autocommit=True,
        ) as connection:
            connection.execute("SET lock_timeout='180s'")
            connection.execute(
                "SELECT pg_advisory_lock(%s,%s)", BENCHMARK_LOCK,
            )
            try:
                yield
            finally:
                connection.execute(
                    "SELECT pg_advisory_unlock(%s,%s)", BENCHMARK_LOCK,
                )
    except psycopg.Error:
        raise DatabaseFixtureError(
            "Test benchmark observation lock failed."
        ) from None
