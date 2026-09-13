"""Command-line interface for the database reset use case."""

import argparse
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.maintenance_cli import add_operator_arguments, cli_errors, maintenance_service
from app.shared.logging import get_logger, setup_logging


@cli_errors
def main() -> None:
    """CLI entrypoint for database flush script."""
    parser = argparse.ArgumentParser(
        description="Flush all projects and tasks from the EPPM database."
    )
    add_operator_arguments(parser)
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Bypass interactive confirmation prompt.",
    )

    args = parser.parse_args()
    setup_logging()

    if not args.yes:
        confirm = (
            input(
                "[!] Are you sure you want to flush ALL projects and tasks from the database? (y/N): "
            )
            .strip()
            .lower()
        )
        if confirm != "y":
            get_logger(__name__).info("Flush operation cancelled.")
            sys.exit(0)

    result = maintenance_service(args).flush()
    get_logger(__name__).info("Database reset completed: %s", result)


if __name__ == "__main__":
    main()
