"""Compatibility exports for database utilities now owned by infrastructure."""

import argparse
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.infrastructure.database.bulk_seed import (
    PROJECT_SUFFIXES,
    TASK_TEMPLATES,
    TASK_DEFAULT_DURATIONS_DAYS,
    MILESTONE_TEMPLATES,
    PROJECT_STATUSES,
    seed_database,
)


from app.main import create_maintenance_service
from scripts.maintenance_cli import cli_errors
from app.shared.logging import get_logger, setup_logging
from app.application.ports.maintenance import SeedRequest


@cli_errors
def main() -> None:
    """CLI entrypoint for database seed script."""
    parser = argparse.ArgumentParser(
        description="Seed the EPPM database with realistic projects and tasks."
    )
    parser.add_argument(
        "--projects",
        type=int,
        default=1000,
        help="Number of projects to generate (default: 1000).",
    )
    parser.add_argument(
        "--min-tasks",
        type=int,
        default=0,
        help="Minimum tasks per project (default: 0).",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=15,
        help="Maximum tasks per project (default: 15).",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Optional path to SQLite database file.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        default=True,
        help="Flush existing records and execute seeder.py before generating projects (default: True).",
    )
    parser.add_argument(
        "--no-clean",
        action="store_false",
        dest="clean",
        help="Do not flush existing records before seeding.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible generation (default: 42).",
    )

    args = parser.parse_args()

    setup_logging()
    result = create_maintenance_service(args.db_path).seed_projects(
        SeedRequest(
            projects=args.projects,
            min_tasks=args.min_tasks,
            max_tasks=args.max_tasks,
            clean_first=args.clean,
            random_seed=args.seed,
        )
    )
    get_logger(__name__).info("Seeding completed: %s", result)


if __name__ == "__main__":
    main()
