"""Own disposable migrated templates and clones on an explicit test server."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
import logging
import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.infrastructure.postgresql.errors import MigrationError
from app.infrastructure.postgresql.migration import (
    discover_migrations,
    migrate,
)
from app.shared.config.database import validate_database_url


LOGGER = logging.getLogger(__name__)
DATABASE_PRIVILEGES = frozenset({"CONNECT", "CREATE", "TEMPORARY"})
MAINTENANCE_DATABASE = "postgres"


class DatabaseFixtureError(RuntimeError):
    """Report a driver failure without connection strings or SQL payloads."""


@dataclass(frozen=True)
class PostgreSQLFixture:
    """Describe one owned test database without representing credentials."""

    name: str
    operator_url: str = field(repr=False)
    runtime_url: str = field(repr=False)


@dataclass(frozen=True)
class _DatabaseMetadata:
    owner: str
    connection_limit: int
    grants: tuple[tuple[str, str, bool], ...]
    settings: tuple[tuple[str | None, str, str], ...] = field(repr=False)


def database_url(original: str, name: str) -> str:
    """Replace a validated URL's database without changing credentials.

    Args:
        original: PostgreSQL URL with no database query override.
        name: Generated database identifier.

    Returns:
        A URL pointing to the generated database.

    Raises:
        ValueError: URL, generated name, or query overrides are unsafe.
    """
    __tracebackhide__ = True
    validate_database_url(original)
    if re.fullmatch(r"[A-Za-z0-9_-]{1,63}", name) is None:
        raise ValueError("Invalid generated test database identifier.")
    parsed = urlsplit(original)
    if any(key in {"dbname", "service"} for key, _ in parse_qsl(parsed.query)):
        raise ValueError("Test URLs cannot override databases or services.")
    return urlunsplit(parsed._replace(path=f"/{name}"))


def _options(url: str) -> dict[str, str]:
    __tracebackhide__ = True
    try:
        return conninfo_to_dict(url)
    except psycopg.ProgrammingError:
        raise ValueError("Invalid test connection coordinates.") from None


class DatabaseTemplateFactory:
    """Keep migration-only templates and independently disposable test clones.

    Args:
        operator_url: Explicit test-server operator connection URL.
        runtime_url: Same test server with a distinct restricted login.
        worker: Short identifier distinguishing the owning pytest worker.

    Raises:
        ValueError: Connection coordinates or worker identity are invalid.
        MigrationError: Migration sources cannot be discovered consistently.
    """

    def __init__(
        self, operator_url: str, runtime_url: str, *, worker: str = "serial",
    ) -> None:
        __tracebackhide__ = True
        database_url(operator_url, MAINTENANCE_DATABASE)
        database_url(runtime_url, MAINTENANCE_DATABASE)
        operator = _options(operator_url)
        runtime = _options(runtime_url)
        if operator.get("user") == runtime.get("user"):
            raise ValueError("Test setup and runtime users must be different.")
        coordinates = ("host", "hostaddr", "dbname")
        if any(operator.get(key) != runtime.get(key) for key in coordinates):
            raise ValueError("Test connections must select the same server.")
        if operator.get("port", "5432") != runtime.get("port", "5432"):
            raise ValueError("Test connections must select the same server.")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,16}", worker) is None:
            raise ValueError("Invalid test worker identity.")
        self._operator_url = operator_url
        self._runtime_url = runtime_url
        self._maintenance_url = make_conninfo(
            operator_url, dbname=MAINTENANCE_DATABASE,
        )
        self._prefix = f"eppm_test_{worker}_{uuid4().hex[:12]}"
        self._owned: dict[str, PostgreSQLFixture] = {}
        self._template: PostgreSQLFixture | None = None
        self._metadata: _DatabaseMetadata | None = None
        self._closed = False
        self._ledger = tuple(
            (item.version, item.name, item.checksum)
            for item in discover_migrations()
        )

    @contextmanager
    def _connect(
        self, url: str, *, autocommit: bool = False,
    ) -> Iterator[psycopg.Connection]:
        # Pytest must not show the secret-bearing argument in traceback locals.
        __tracebackhide__ = True
        try:
            with psycopg.connect(url, autocommit=autocommit) as connection:
                yield connection
        except psycopg.Error as error:
            kind = type(error).__name__
            LOGGER.error("Owned test database operation failed (%s)", kind)
            raise DatabaseFixtureError(
                f"Owned test database operation failed ({kind})."
            ) from None

    @property
    def owned_names(self) -> frozenset[str]:
        """Return owned identifiers for diagnostics without credentials.

        Returns:
            Immutable exact identifiers successfully created by this factory.
        """
        return frozenset(self._owned)

    def _create(self, *, template: str | None = None) -> PostgreSQLFixture:
        if self._closed:
            raise RuntimeError("The test database factory is closed.")
        name = f"{self._prefix}_{uuid4().hex}"[:63]
        statement = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
        if template is not None:
            if template not in self._owned:
                raise ValueError("Only an owned template may be cloned.")
            statement += sql.SQL(" TEMPLATE {}").format(
                sql.Identifier(template),
            )
        with self._connect(
            self._maintenance_url, autocommit=True,
        ) as connection:
            connection.execute(statement)
        fixture = PostgreSQLFixture(
            name, database_url(self._operator_url, name),
            database_url(self._runtime_url, name),
        )
        self._owned[name] = fixture
        LOGGER.info("Created owned test database %s", name)
        return fixture

    def _drop(self, name: str) -> None:
        if name not in self._owned:
            raise ValueError("Refusing cleanup of an unowned database.")
        with self._connect(
            self._maintenance_url, autocommit=True,
        ) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name),
                ),
            )
        del self._owned[name]
        LOGGER.info("Removed owned test database %s", name)

    def _verify_ledger(self, connection: psycopg.Connection) -> None:
        rows = connection.execute(
            "SELECT version, name, checksum FROM eppm.schema_migration "
            "ORDER BY version"
        ).fetchall()
        if tuple(rows) != self._ledger:
            raise ValueError("Test template migration ledger is incomplete.")

    def _snapshot_metadata(self, name: str) -> _DatabaseMetadata:
        with self._connect(self._maintenance_url) as connection:
            owner, connection_limit = connection.execute(
                "SELECT pg_catalog.pg_get_userbyid(datdba), datconnlimit "
                "FROM pg_catalog.pg_database WHERE datname=%s", (name,),
            ).fetchone()
            grants = connection.execute(
                "SELECT coalesce(r.rolname,'PUBLIC'), a.privilege_type, "
                "a.is_grantable FROM pg_catalog.pg_database d "
                "CROSS JOIN LATERAL pg_catalog.aclexplode(coalesce("
                "d.datacl,pg_catalog.acldefault('d',d.datdba))) a "
                "LEFT JOIN pg_catalog.pg_roles r ON r.oid=a.grantee "
                "WHERE d.datname=%s ORDER BY 1,2,3", (name,),
            ).fetchall()
            settings = connection.execute(
                "SELECT CASE WHEN s.setrole=0 THEN NULL ELSE "
                "pg_catalog.pg_get_userbyid(s.setrole) END, "
                "unnest(s.setconfig) FROM pg_catalog.pg_db_role_setting s "
                "JOIN pg_catalog.pg_database d ON d.oid=s.setdatabase "
                "WHERE d.datname=%s ORDER BY 1,2", (name,),
            ).fetchall()
        return _DatabaseMetadata(
            owner, connection_limit, tuple(grants),
            tuple(
                (role, *setting.split("=", 1)) for role, setting in settings
            ),
        )

    @staticmethod
    def _grantee(name: str) -> sql.Composable:
        return sql.SQL("PUBLIC") if name == "PUBLIC" else sql.Identifier(name)

    def _apply_metadata(self, name: str, metadata: _DatabaseMetadata) -> None:
        with self._connect(
            self._maintenance_url, autocommit=True,
        ) as connection:
            connection.execute(sql.SQL(
                "ALTER DATABASE {} CONNECTION LIMIT {}"
            ).format(
                sql.Identifier(name), sql.Literal(metadata.connection_limit),
            ))
            for grantee in ("PUBLIC", metadata.owner):
                connection.execute(
                    sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(
                        sql.Identifier(name), self._grantee(grantee),
                    ),
                )
            for grantee, privilege, grantable in metadata.grants:
                if privilege not in DATABASE_PRIVILEGES:
                    raise ValueError("Unexpected test database privilege.")
                statement = sql.SQL("GRANT {} ON DATABASE {} TO {}").format(
                    sql.SQL(privilege), sql.Identifier(name),
                    self._grantee(grantee),
                )
                if grantable:
                    statement += sql.SQL(" WITH GRANT OPTION")
                connection.execute(statement)
            self._apply_settings(connection, name, metadata.settings)
        if self._snapshot_metadata(name) != metadata:
            raise ValueError("Test clone database configuration differs.")

    @staticmethod
    def _apply_settings(
        connection: psycopg.Connection, name: str,
        settings: tuple[tuple[str | None, str, str], ...],
    ) -> None:
        for role, key, value in settings:
            connection.execute("SELECT pg_catalog.set_config(%s,%s,false)",
                               (key, value))
            target = sql.SQL("ALTER DATABASE {}").format(sql.Identifier(name))
            if role is not None:
                target = sql.SQL("ALTER ROLE {} IN DATABASE {}").format(
                    sql.Identifier(role), sql.Identifier(name),
                )
            connection.execute(target + sql.SQL(" SET {} FROM CURRENT").format(
                sql.Identifier(key),
            ))

    def _ensure_template(self) -> PostgreSQLFixture:
        if self._template is not None:
            return self._template
        template = self._create()
        ready = False
        try:
            self._migrate(template)
            with self._connect(template.operator_url) as connection:
                self._verify_ledger(connection)
            metadata = self._snapshot_metadata(template.name)
            with self._connect(
                self._maintenance_url, autocommit=True,
            ) as connection:
                connection.execute(sql.SQL(
                    "ALTER DATABASE {} ALLOW_CONNECTIONS false"
                ).format(sql.Identifier(template.name)))
            self._template, self._metadata = template, metadata
            ready = True
            return template
        finally:
            if not ready:
                self._drop(template.name)

    @staticmethod
    def _migrate(fixture: PostgreSQLFixture) -> None:
        try:
            migrate(fixture.operator_url)
        except MigrationError:
            raise DatabaseFixtureError(
                "Test database migration failed."
            ) from None

    @contextmanager
    def empty(self) -> Iterator[PostgreSQLFixture]:
        """Yield an unmigrated database and drop only that owned database.

        Yields:
            Distinct operator/runtime coordinates for an empty database.

        Raises:
            RuntimeError: The factory is closed.
            DatabaseFixtureError: Database creation or cleanup failed.
        """
        fixture = self._create()
        try:
            yield fixture
        finally:
            self._drop(fixture.name)

    @contextmanager
    def fresh(self) -> Iterator[PostgreSQLFixture]:
        """Yield a separately created database migrated through the real path.

        Yields:
            A disposable freshly migrated database for reference runs.

        Raises:
            DatabaseFixtureError: Creation, migration or cleanup failed.
        """
        with self.empty() as fixture:
            self._migrate(fixture)
            yield fixture

    @contextmanager
    def clone(self) -> Iterator[PostgreSQLFixture]:
        """Yield one independent clone of the closed migration-only template.

        Yields:
            A migrated database with a fresh lifecycle identity.

        Raises:
            ValueError: Template or clone metadata does not match.
            DatabaseFixtureError: Migration, clone or cleanup I/O failed.
        """
        template = self._ensure_template()
        fixture = self._create(template=template.name)
        try:
            assert self._metadata is not None
            self._apply_metadata(fixture.name, self._metadata)
            with self._connect(fixture.operator_url) as connection:
                self._verify_ledger(connection)
                connection.execute(
                    "UPDATE eppm.database_identity SET epoch=gen_random_uuid()"
                )
            yield fixture
        finally:
            self._drop(fixture.name)

    def close(self) -> None:
        """Close the factory, dropping owned clones before their template.

        Raises:
            DatabaseFixtureError: An owned database could not be removed.
        """
        self._closed = True
        with ExitStack() as cleanup:
            for name in tuple(self._owned):
                cleanup.callback(self._drop, name)
        self._template = None
