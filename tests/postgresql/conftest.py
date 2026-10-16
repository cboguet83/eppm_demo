"""Provision each test database separately; never reset application storage."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
import shutil
from secrets import token_bytes
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from app.infrastructure.postgresql.backup import PostgresTools
from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.authorization import ActorBinding, configure_signing_key
from app.application.services.access import AuthorizationPolicy, SessionLimits
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor
from app.shared.config.database import DatabaseConfig
from tests.postgresql.template_database import (
    DatabaseTemplateFactory,
    PostgreSQLFixture,
    database_url,
)


@pytest.fixture(scope="session")
def database_factory() -> Iterator[DatabaseTemplateFactory]:
    """Own one lazy template factory for this pytest process.

    Yields:
        A worker-local factory bound only to explicit test credentials.
    """
    operator = os.environ.get("POSTGRES_TEST_ADMIN_URL")
    runtime = os.environ.get("POSTGRES_TEST_RUNTIME_URL")
    if not operator or not runtime:
        pytest.skip(
            "Set explicit POSTGRES_TEST_ADMIN_URL and "
            "POSTGRES_TEST_RUNTIME_URL for real PostgreSQL tests."
        )
    factory = DatabaseTemplateFactory(
        operator, runtime,
        worker=os.environ.get("PYTEST_XDIST_WORKER", "serial"),
    )
    try:
        yield factory
    finally:
        factory.close()


@pytest.fixture
def empty_database(
    database_factory: DatabaseTemplateFactory,
) -> Iterator[PostgreSQLFixture]:
    """Yield a genuinely unmigrated database independent of ordinary tests."""
    with database_factory.empty() as database:
        yield database


@pytest.fixture
def pg_database(
    database_factory: DatabaseTemplateFactory, request: pytest.FixtureRequest,
) -> Iterator[PostgreSQLFixture]:
    """Yield a fresh migrated database or a disposable migration-only clone."""
    mode = request.config.getoption("postgres_test_db_mode")
    preparation = (
        database_factory.clone() if mode == "template"
        else database_factory.fresh()
    )
    with preparation as database:
        yield database


@pytest.fixture
def clients():
    """Use installed native clients or the explicitly selected test container."""
    container = os.environ.get('POSTGRES_TEST_CLIENT_CONTAINER')
    if container:
        class DockerClients(PostgresTools):
            def _environment(self, url):
                return super()._environment(url) | {'PGHOST': '127.0.0.1', 'PGPORT': '5432'}
        variables = ('PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD')
        return DockerClients(('docker', 'exec', '-i', *(part for name in variables for part in ('--env', name)), container))
    if not shutil.which('pg_dump') or not shutil.which('pg_restore'):
        pytest.skip('Install PostgreSQL clients or set POSTGRES_TEST_CLIENT_CONTAINER to the isolated test server container.')
    return PostgresTools()


@pytest.fixture
def restore_target(pg_database):
    """Create and clean up only a distinct random restore target."""
    name = 'eppm_test_restore_' + uuid4().hex
    maintenance = database_url(pg_database.operator_url, 'postgres')
    with psycopg.connect(maintenance, autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        yield PostgreSQLFixture(name, database_url(pg_database.operator_url, name), database_url(pg_database.runtime_url, name))
    finally:
        with psycopg.connect(maintenance, autocommit=True) as connection:
            connection.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


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
def authorized(pg_database: PostgreSQLFixture) -> Iterator[AuthorizedFixture]:
    """Seed actual accounts/sessions/grants as setup; exercise the restricted role."""
    with authorized_database(pg_database) as fixture:
        yield fixture


@contextmanager
def authorized_database(
    pg_database: PostgreSQLFixture,
) -> Iterator[AuthorizedFixture]:
    """Seed and close an independent authorized test database.

    Args:
        pg_database: One test-owned migrated database, never shared state.

    Yields:
        The normal restricted pool and independently generated signing key.
    """
    key = token_bytes(32)
    configure_signing_key(pg_database.operator_url, key.hex())
    with psycopg.connect(pg_database.operator_url) as operator:
        operator.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
        operator.execute("INSERT INTO eppm.project(name) VALUES ('Editable'),('Read only'),('Hidden')")
        operator.execute('''INSERT INTO eppm.project_plan
            (project_id,version,name,status_id,is_current,author,created_at)
            SELECT id,1,'Initial plan',3,true,'test setup',CURRENT_TIMESTAMP FROM eppm.project''')
        for user_id in range(1, 6):
            operator.execute("INSERT INTO eppm.app_user(id,status,created_at,updated_at) VALUES (%s,'active',900,900)", (user_id,))
            operator.execute("INSERT INTO eppm.app_session VALUES (%s,%s,950,2000,980,false,false)",
                             (f"session-{user_id}", user_id))
        operator.execute("SELECT setval(pg_get_serial_sequence('eppm.app_user','id'),(SELECT max(id) FROM eppm.app_user))")
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
