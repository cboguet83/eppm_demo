"""Command boundary for installing the existing default demo catalog."""

import argparse
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.operator_services import create_maintenance_service
from app.shared.logging import get_logger, setup_logging
from scripts.maintenance_cli import cli_errors


@cli_errors
def main() -> None:
    """Install defaults or explicitly replace them when --force is supplied."""
    parser = argparse.ArgumentParser(
        description="Seed default EPPM schema, taxonomy, and sample data."
    )
    parser.add_argument("--db-path", default=None, help="Optional SQLite database path.")
    parser.add_argument(
        "--force", action="store_true", help="Replace existing data after backing it up."
    )
    args = parser.parse_args()
    setup_logging()
    create_maintenance_service(args.db_path).seed_defaults(force=args.force)
    get_logger(__name__).info("Database seeding completed successfully.")


if __name__ == "__main__":
    main()
