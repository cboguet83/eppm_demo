"""Explicit PostgreSQL role provisioning, migration and schema verification."""

import argparse
import os

from dotenv import load_dotenv
import psycopg
from psycopg import sql

from app.infrastructure.postgresql.errors import MigrationError, SchemaCompatibilityError
from app.infrastructure.postgresql.migration import check_schema, migrate
from app.infrastructure.postgresql.authorization import configure_signing_key
from app.shared.config.database import validate_database_url
from app.shared.logging import get_logger, setup_logging

logger = get_logger(__name__)


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


def main() -> None:
    """Load operator settings only from explicit environment or an explicit file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", help="Ignored operator environment file; never loaded implicitly")
    parser.add_argument("--url-variable", default="DATABASE_OPERATOR_URL")
    parser.add_argument("command", choices=("provision", "migrate", "check", "configure-security"))
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
        else:
            with psycopg.connect(url, autocommit=True, connect_timeout=5) as connection:
                check_schema(connection)
    except (ValueError, psycopg.Error, MigrationError, SchemaCompatibilityError):
        parser.exit(1, "PostgreSQL operator command failed. Check configuration, role privileges and schema compatibility.\n")


if __name__ == "__main__":
    main()
