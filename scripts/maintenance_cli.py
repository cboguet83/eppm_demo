"""Safe error handling shared by the maintenance command boundaries."""

from collections.abc import Callable
import argparse
from functools import wraps
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from app.application.exceptions import DatabaseMaintenanceError
from app.application.services.maintenance import MaintenanceService
from app.operator_services import create_maintenance_service


def add_operator_arguments(parser: argparse.ArgumentParser) -> None:
    """Add explicit operator configuration without exposing credential arguments."""
    parser.add_argument('--env-file', help='Explicit operator environment file; never loaded implicitly.')
    parser.add_argument('--url-variable', default='DATABASE_OPERATOR_URL')
    parser.add_argument('--backup-directory', type=Path)


def maintenance_service(arguments: argparse.Namespace) -> MaintenanceService:
    """Load only a named operator environment and compose native maintenance."""
    if arguments.env_file:
        load_dotenv(arguments.env_file, override=True)
    return create_maintenance_service(
        os.environ.get(arguments.url_variable, ''), backup_directory=arguments.backup_directory,
    )


def cli_errors[**P](command: Callable[P, None]) -> Callable[P, None]:
    """Report expected validation/storage failures without printing stack traces."""

    @wraps(command)
    def run(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            command(*args, **kwargs)
        except (DatabaseMaintenanceError, ValueError) as error:
            logging.getLogger(command.__module__).error("%s", error)
            raise SystemExit(1) from None

    return run
