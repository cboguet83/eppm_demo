"""Explicit, atomic, checksum-verified migrations protected by a database lock."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

import psycopg

from app.infrastructure.postgresql.errors import MigrationError, SchemaCompatibilityError
from app.shared.config.database import validate_database_url

MIGRATION_DIRECTORY = Path(__file__).with_name("migrations")
MIGRATION_LOCK = 0x4550504D4D494752
_FILENAME = re.compile(r"(?P<version>[0-9]{4})_[a-z][a-z0-9_]*\.sql\Z")


@dataclass(frozen=True)
class Migration:
    """Immutable bytes decoded and checksummed before obtaining the database lock."""

    version: int
    name: str
    checksum: str
    sql: str


def discover_migrations(directory: Path = MIGRATION_DIRECTORY) -> tuple[Migration, ...]:
    """Read consecutively numbered UTF-8 SQL files, rejecting gaps and duplicates."""
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME.fullmatch(path.name)
        if match is None or int(match["version"]) != len(migrations) + 1:
            raise MigrationError("Migration files must have consecutive, unique versions.")
        content = path.read_bytes()
        try:
            source = content.decode("utf-8")
        except UnicodeDecodeError:
            raise MigrationError("Migration files must be valid UTF-8.") from None
        if not source.strip():
            raise MigrationError("Migration files cannot be empty.")
        checksum_content = content
        if path.name == '0040_pool_hierarchy.sql':
            checksum_content += Path(__file__).with_name('pool_hierarchy_migration.py').read_bytes()
        migrations.append(Migration(len(migrations) + 1, path.name, sha256(checksum_content).hexdigest(), source))
    if not migrations:
        raise MigrationError("No migration files were found.")
    return tuple(migrations)


def _verify_ledger(
    connection: psycopg.Connection, migrations: tuple[Migration, ...], *, complete: bool,
) -> int:
    rows = connection.execute(
        "SELECT version, name, checksum FROM eppm.schema_migration ORDER BY version"
    ).fetchall()
    expected = [(migration.version, migration.name, migration.checksum) for migration in migrations]
    if rows != expected[:len(rows)] or len(rows) > len(expected) or (complete and rows != expected):
        raise SchemaCompatibilityError("Database schema does not match this application release.")
    return len(rows)


def check_schema(connection: psycopg.Connection) -> None:
    """Read compatibility metadata only; never create or repair database objects."""
    try:
        _verify_ledger(connection, discover_migrations(), complete=True)
    except psycopg.Error:
        raise SchemaCompatibilityError("Apply the operator migrations before starting the application.") from None


def migrate(url: str, *, directory: Path = MIGRATION_DIRECTORY) -> tuple[str, ...]:
    """Apply pending SQL and ledger entries atomically using operator credentials.

    Args:
        url: Explicit operator URL, never read from runtime configuration.
        directory: Ordered migration package; override only for isolated checks.

    Returns:
        Names of applied migrations, empty when already current.
    """
    validate_database_url(url)
    migrations = discover_migrations(directory)
    current_name = "initialization"
    try:
        with psycopg.connect(url, autocommit=True, connect_timeout=5) as connection:
            with connection.transaction():
                connection.execute("SET LOCAL lock_timeout = '30s'")
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
                connection.execute("CREATE SCHEMA IF NOT EXISTS eppm")
                connection.execute("REVOKE ALL ON SCHEMA eppm FROM PUBLIC")
                connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS eppm.schema_migration (
                        version integer PRIMARY KEY CHECK (version > 0),
                        name text NOT NULL UNIQUE,
                        checksum text NOT NULL CHECK (length(checksum) = 64),
                        applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
                    )
                """)
                applied = _verify_ledger(connection, migrations, complete=False)
                for migration in migrations[applied:]:
                    current_name = migration.name
                    connection.execute(migration.sql)
                    if migration.name == '0040_pool_hierarchy.sql':
                        from app.infrastructure.postgresql.pool_hierarchy_migration import convert_pool_groups
                        convert_pool_groups(connection)
                    connection.execute(
                        "INSERT INTO eppm.schema_migration(version, name, checksum) VALUES (%s, %s, %s)",
                        (migration.version, migration.name, migration.checksum),
                    )
                return tuple(migration.name for migration in migrations[applied:])
    except psycopg.Error as error:
        # Version and SQLSTATE are safe diagnostics. Never include driver messages,
        # which can contain connection credentials, SQL, or application payloads.
        raise MigrationError(
            f"Database migration failed; no changes were applied. "
            f"Migration: {current_name}; SQLSTATE: {error.sqlstate or 'unavailable'}."
        ) from None
