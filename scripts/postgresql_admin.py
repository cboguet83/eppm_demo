"""Explicit PostgreSQL setup, archives and backed-up demo maintenance."""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
import psycopg
from psycopg import sql

from app.infrastructure.postgresql.errors import DatabaseUnavailableError, MigrationError, SchemaCompatibilityError, TransactionRetryError
from app.infrastructure.postgresql.migration import check_schema, migrate
from app.infrastructure.postgresql.authorization import configure_signing_key
from app.infrastructure.postgresql.backup import PostgresBackup, PostgresTools, restore_database
from app.infrastructure.postgresql import maintenance
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.application.exceptions import DatabaseMaintenanceError
from app.shared.config.database import validate_database_url
from app.shared.logging import get_logger, setup_logging

logger = get_logger(__name__)
MAINTENANCE_COMMANDS = ('seed-defaults', 'seed-pools', 'reset', 'clear-allocations', 'counts')


def provision_runtime(url: str, password: str) -> None:
    """Create the non-owner runtime roles explicitly using operator credentials.

    This is cluster setup, not an ordinary application or migration operation.
    Re-running verifies existing roles and does not rotate existing passwords.
    """
    validate_database_url(url)
    if len(password) < 32 or any(character.isspace() for character in password):
        raise ValueError("Configure a separate random runtime password of at least 32 characters.")
    with psycopg.connect(url, autocommit=True, connect_timeout=5) as connection:
        with connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(4994576949004554828)")
            roles = dict(connection.execute("""
                SELECT rolname, rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole
                FROM pg_roles WHERE rolname IN ('eppm_runtime', 'eppm_app')
            """))
            if any(roles.values()):
                raise ValueError("Existing runtime roles have unsafe privileges; review their provisioning.")
            if "eppm_runtime" not in roles:
                connection.execute("CREATE ROLE eppm_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS")
            if "eppm_app" not in roles:
                connection.execute(sql.SQL(
                    "CREATE ROLE eppm_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}"
                ).format(sql.Literal(password)))
            connection.execute("GRANT eppm_runtime TO eppm_app")


def main(*, archive_tools: PostgresTools | None = None) -> None:
    """Load explicit operator settings, with injectable installed archive clients."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", help="Ignored operator environment file; never loaded implicitly")
    parser.add_argument("--url-variable", default="DATABASE_OPERATOR_URL")
    parser.add_argument("--backup-directory", type=Path, default=Path('.local/backups'))
    parser.add_argument("--archive", type=Path, help="Existing PostgreSQL archive for an empty restore target")
    parser.add_argument('--force', action='store_true', help='Replace the demo and references when seeding defaults')
    parser.add_argument('--without-projects', action='store_true', help='Install the default catalog without example projects')
    parser.add_argument('--all-references', action='store_true', help='Include demo reference cleanup in an explicit reset')
    parser.add_argument('--year', type=int, help='Scenario year; defaults to the current year')
    parser.add_argument('--seed', type=int, default=20260908, help='Pool scenario random seed')
    parser.add_argument('--apply', action='store_true', help='Apply the pool scenario preview after creating an archive')
    parser.add_argument("command", choices=("provision", "migrate", "check", "configure-security", "backup", "restore", *MAINTENANCE_COMMANDS))
    arguments = parser.parse_args()
    if arguments.env_file:
        load_dotenv(arguments.env_file, override=True)
    setup_logging()
    try:
        url = os.environ.get(arguments.url_variable, "")
        validate_database_url(url)
        if arguments.command == "provision":
            provision_runtime(url, os.environ.get("EPPM_RUNTIME_PASSWORD", ""))
        elif arguments.command == "migrate":
            names = migrate(url)
            logger.info("PostgreSQL migrations applied: %s", ", ".join(names) or "already current")
        elif arguments.command == "configure-security":
            configure_signing_key(url, os.environ.get("DATABASE_CONTEXT_KEY", ""))
        elif arguments.command == "backup":
            PostgresBackup(url, arguments.backup_directory, tools=archive_tools).create('operator')
        elif arguments.command == "restore":
            if arguments.archive is None:
                raise ValueError('Specify a PostgreSQL archive for restoration.')
            restore_database(arguments.archive, url, tools=archive_tools)
        elif arguments.command in MAINTENANCE_COMMANDS:
            _maintenance(arguments, url, archive_tools)
        else:
            with psycopg.connect(url, autocommit=True, connect_timeout=5) as connection:
                check_schema(connection)
    except (ValueError, psycopg.Error, MigrationError, SchemaCompatibilityError, DatabaseMaintenanceError,
            DatabaseUnavailableError, TransactionRetryError):
        parser.exit(1, "PostgreSQL operator command failed. Check configuration, role privileges, schema compatibility and any archive or restore target.\n")


def _maintenance(arguments: argparse.Namespace, url: str, archive_tools: PostgresTools | None) -> None:
    """Dispatch explicit maintenance only after checking the installed schema."""
    database = OperatorDatabase(url)
    database.run(check_schema)
    backup = PostgresBackup(url, arguments.backup_directory, tools=archive_tools)
    if arguments.command == 'seed-defaults':
        result = maintenance.seed_defaults(database, backup, force=arguments.force,
            include_projects=not arguments.without_projects, year=arguments.year)
    elif arguments.command == 'seed-pools':
        result = maintenance.seed_pool_scenarios(database, backup, year=arguments.year, seed=arguments.seed, apply=arguments.apply)
    elif arguments.command == 'reset':
        result = maintenance.reset_database(database, backup, flush_all=arguments.all_references)
    elif arguments.command == 'clear-allocations':
        result = maintenance.clear_pool_allocations(database, backup)
    else:
        result = maintenance.counts(database)
    logger.info('PostgreSQL %s result: %s', arguments.command, result)


if __name__ == "__main__":
    main()
