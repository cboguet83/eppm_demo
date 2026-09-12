"""Provision each test database separately; never reset application storage."""

from dataclasses import dataclass, field
import os
from secrets import token_bytes
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb
import pytest

from app.infrastructure.postgresql.migration import migrate
from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.authorization import ActorBinding, configure_signing_key
from app.application.services.access import AuthorizationPolicy, SessionLimits
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor
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


@dataclass(frozen=True)
class AuthorizedFixture:
    """Real identities with disjoint scopes and one separate setup connection."""

    setup: PostgreSQLFixture
    database: Database
    key: bytes = field(repr=False)

    def binding(self, user_id: int = 1, *, now: int = 1000,
                limits: SessionLimits | None = None) -> ActorBinding:
        """Create trusted test-server context; never bypass database checks."""
        access = BusinessAccess(Actor(user_id, f"session-{user_id}", f"request-{user_id}"),
                                AuthorizationPolicy(lambda: now, limits or SessionLimits()))
        return ActorBinding(access, self.key)

    def query(self, source, parameters=(), *, user_id: int = 1, write: bool = False):
        """Run an entire actor-bound operation through the production pool."""
        def operation(connection):
            cursor = connection.execute(source, parameters)
            return cursor.fetchall() if cursor.description else []
        return self.database.run(operation, write=write, bind=self.binding(user_id))


@pytest.fixture
def authorized(pg_database: PostgreSQLFixture) -> AuthorizedFixture:
    """Seed actual accounts/sessions/grants as setup; exercise the restricted role."""
    key = token_bytes(32)
    configure_signing_key(pg_database.operator_url, key.hex())
    with psycopg.connect(pg_database.operator_url) as operator:
        operator.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
        operator.execute("INSERT INTO eppm.project(name) VALUES ('Editable'),('Read only'),('Hidden')")
        for user_id in range(1, 6):
            operator.execute("INSERT INTO eppm.app_user(id,status,created_at,updated_at) VALUES (%s,'active',900,900)", (user_id,))
            operator.execute("INSERT INTO eppm.app_session VALUES (%s,%s,950,2000,980,false,false)",
                             (f"session-{user_id}", user_id))
        for user_id, role, scope in (
            (1, "project_editor", {"kind": "projects", "project_ids": [1]}),
            (1, "project_viewer", {"kind": "projects", "project_ids": [2]}),
            (2, "project_viewer", {"kind": "projects", "project_ids": [3]}),
            (4, "business_admin", {"kind": "all"}),
            (5, "access_admin", {"kind": "all"}),
        ):
            operator.execute("""INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
                VALUES (%s,%s,%s,900,'test setup')""", (user_id, role, Jsonb(scope)))
    resource = Database(DatabaseConfig(pg_database.runtime_url, pool_min=1, pool_max=2))
    resource.open()
    try:
        yield AuthorizedFixture(pg_database, resource, key)
    finally:
        resource.close()
