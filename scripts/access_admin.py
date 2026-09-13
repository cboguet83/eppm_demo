"""Deployment-only application account inspection, bootstrap and recovery commands."""

from argparse import ArgumentParser
import json
import os
import sys

from dotenv import load_dotenv

from app.domain.access.models import AccessStorageError
from app.infrastructure.postgresql.errors import MigrationError, SchemaCompatibilityError
from app.infrastructure.postgresql.migration import migrate
from app.operator_services import create_deployment_access_service
from app.shared.logging import get_logger, setup_logging


def parser() -> ArgumentParser:
    """Expose targeted deployment operations without public authentication shortcuts."""
    result = ArgumentParser(description=__doc__, allow_abbrev=False)
    result.add_argument('--env-file', help='Explicit operator environment file; never loaded implicitly.')
    result.add_argument('--url-variable', default='DATABASE_OPERATOR_URL')
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="Apply idempotent database migrations before starting the application.")
    pending = commands.add_parser("pending-accounts", help="List pending application user references for verification.")
    pending.add_argument("--after-id", type=int, default=0, help="Continue after this application user reference.")
    pending.add_argument("--limit", type=int, default=200, help="Maximum accounts to return, from 1 to 200.")
    bootstrap = commands.add_parser("bootstrap-admin", help="Appoint the first verified access administrator once.")
    bootstrap.add_argument("--user-id", type=int, required=True)
    recovery = commands.add_parser("recover-admin", help="Recover a verified administrator with an audit reason.")
    recovery.add_argument("--user-id", type=int, required=True)
    recovery.add_argument("--reason", required=True)
    return result


def run(argv: list[str] | None = None) -> int:
    """Use separate PostgreSQL operator authority and record the OS audit context."""
    args = parser().parse_args(argv)
    setup_logging(stream=sys.stderr)
    logger = get_logger(__name__)
    try:
        if args.env_file:
            load_dotenv(args.env_file, override=True)
        url = os.environ.get(args.url_variable, '')
        if args.command == "migrate":
            migrate(url)
            logger.info("Application database migrations completed.")
            return 0
        service = create_deployment_access_service(url)
        if args.command == "pending-accounts":
            # Structured command output, not application diagnostics or identity tokens.
            sys.stdout.write(json.dumps(service.pending_accounts(after_id=args.after_id, limit=args.limit),
                                       ensure_ascii=True) + "\n")
        elif args.command == "bootstrap-admin":
            service.bootstrap(args.user_id)
            logger.info("Initial access administrator appointed: user_id=%d", args.user_id)
        elif args.command == "recover-admin":
            service.recover(args.user_id, args.reason)
            logger.info("Access administrator recovered: user_id=%d", args.user_id)
        return 0
    except ValueError as error:
        logger.error("%s", error)
    except (OSError, AccessStorageError, MigrationError, SchemaCompatibilityError):
        logger.error('Access operation failed. Verify PostgreSQL configuration, migrations and operator permissions.')
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
