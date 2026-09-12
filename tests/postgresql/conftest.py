"""Provision each test database separately; never reset application storage."""

from dataclasses import dataclass, field
import os
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from app.infrastructure.postgresql.migration import migrate
from app.infrastructure.postgresql.pool import Database
from app.shared.config.database import DatabaseConfig


@dataclass(frozen=True)
class PostgreSQLFixture:
    """Secret-bearing setup and runtime connection strings, excluded from repr."""

    name: str
    operator_url: str = field(repr=False)
    runtime_url: str = field(repr=False)


def database_url(original: str, name: str) -> str:
    """Replace only the database name in an explicitly supplied test URL."""
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(original)
    return urlunsplit(parsed._replace(path=f"/{name}"))


@pytest.fixture
def empty_database() -> PostgreSQLFixture:
    """Create a random test database with separate owner and runtime connections."""
    operator = os.environ.get("POSTGRES_TEST_ADMIN_URL")
    runtime = os.environ.get("POSTGRES_TEST_RUNTIME_URL")
    if not operator or not runtime:
        pytest.skip("Set explicit POSTGRES_TEST_ADMIN_URL and POSTGRES_TEST_RUNTIME_URL for real PostgreSQL tests.")
    operator_options, runtime_options = conninfo_to_dict(operator), conninfo_to_dict(runtime)
    if operator_options.get("user") == runtime_options.get("user"):
        pytest.fail("Test setup and runtime users must be different.")
    name = "eppm_test_" + uuid4().hex
    maintenance = make_conninfo(operator, dbname="postgres")
    with psycopg.connect(maintenance, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield PostgreSQLFixture(name, database_url(operator, name), database_url(runtime, name))
    finally:
        # The only cleanup target is the random name created above, never an
        # environment-selected application database or an existing volume.
        with psycopg.connect(maintenance, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def pg_database(empty_database: PostgreSQLFixture) -> PostgreSQLFixture:
    """Migrate using operator credentials; callers use the distinct runtime URL."""
    migrate(empty_database.operator_url)
    return empty_database


@pytest.fixture
def database(pg_database: PostgreSQLFixture) -> Database:
    """Open one restricted pool and close all connections before database cleanup."""
    resource = Database(DatabaseConfig(pg_database.runtime_url, pool_min=1, pool_max=2))
    resource.open()
    try:
        yield resource
    finally:
        resource.close()


@pytest.fixture
def probe(pg_database: PostgreSQLFixture) -> PostgreSQLFixture:
    """Transaction probes exercise real commit/rollback without application mocks."""
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("CREATE TABLE eppm.transaction_probe (id integer PRIMARY KEY, value integer NOT NULL)")
        connection.execute("INSERT INTO eppm.transaction_probe VALUES (1, 0), (2, 0)")
        connection.execute("GRANT SELECT, INSERT, UPDATE ON eppm.transaction_probe TO eppm_runtime")
    return pg_database
