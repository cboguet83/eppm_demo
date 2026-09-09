"""Deployment-only application account inspection, bootstrap and recovery commands."""

from argparse import ArgumentParser
import getpass
import json
from pathlib import Path
import secrets
import socket
import sqlite3
import sys
import time

from app.application.services.access import DeploymentAccessService
from app.infrastructure.database.schema_init import init_db
from app.infrastructure.repositories.access import SqliteAccessGateway
from app.shared.config import config
from app.shared.logging import get_logger, setup_logging


def parser() -> ArgumentParser:
    """Expose targeted deployment operations without public authentication shortcuts."""
    result = ArgumentParser(description=__doc__, allow_abbrev=False)
    result.add_argument("--database", default=config.db_path, help="Deployment SQLite database path.")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="Apply idempotent database migrations before starting the application.")
    commands.add_parser("pending-accounts", help="List pending application user references for verification.")
    bootstrap = commands.add_parser("bootstrap-admin", help="Appoint the first verified access administrator once.")
    bootstrap.add_argument("--user-id", type=int, required=True)
    recovery = commands.add_parser("recover-admin", help="Recover a verified administrator with an audit reason.")
    recovery.add_argument("--user-id", type=int, required=True)
    recovery.add_argument("--reason", required=True)
    return result


def run(argv: list[str] | None = None) -> int:
    """Run with the deployment operator's filesystem authority and record OS context."""
    args = parser().parse_args(argv)
    setup_logging(stream=sys.stderr)
    logger = get_logger(__name__)
    try:
        path = str(Path(args.database).resolve())
        if args.command == "migrate":
            init_db(path)
            logger.info("Application database migrations completed.")
            return 0
        if not Path(path).is_file():
            raise ValueError("Database not found. Run migrations on the intended deployment database first.")
        service = DeploymentAccessService(SqliteAccessGateway(path), lambda: int(time.time()),
                                          f"{getpass.getuser()}@{socket.gethostname()}",
                                          lambda: secrets.token_urlsafe(16))
        if args.command == "pending-accounts":
            # Structured command output, not application diagnostics or identity tokens.
            sys.stdout.write(json.dumps(service.pending_accounts(), ensure_ascii=True) + "\n")
        elif args.command == "bootstrap-admin":
            service.bootstrap(args.user_id)
            logger.info("Initial access administrator appointed: user_id=%d", args.user_id)
        elif args.command == "recover-admin":
            service.recover(args.user_id, args.reason)
            logger.info("Access administrator recovered: user_id=%d", args.user_id)
        return 0
    except ValueError as error:
        logger.error("%s", error)
    except (OSError, sqlite3.Error):
        logger.error("Access operation failed. Verify the database path, migrations and operator permissions.")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
