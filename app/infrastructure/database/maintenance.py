"""Adapt existing initialization and maintenance operations to application ports."""

from collections.abc import Callable
from contextlib import closing
from functools import wraps
import logging
import sqlite3

from app.application.exceptions import DatabaseMaintenanceError
from app.application.ports.maintenance import DatabaseCounts, PoolSeedReport, SeedRequest
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.schema_init import init_db
from app.infrastructure.database.seeder import seed_default_data_if_empty
from app.infrastructure.database.bulk_seed import seed_database
from app.infrastructure.database.flush import flush_database
from app.infrastructure.database.pool_scenarios import seed_pool_scenarios

logger = logging.getLogger(__name__)


def maintenance_errors[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """Translate storage, backup, and snapshot failures at the adapter boundary."""

    @wraps(function)
    def run(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except (sqlite3.DatabaseError, OSError, RuntimeError) as error:
            logger.error("Database maintenance failed (%s)", type(error).__name__)
            raise DatabaseMaintenanceError(
                "Database maintenance could not complete. Any pre-operation backup is retained."
            ) from error

    return run


class SqliteMaintenanceGateway:
    """Use the existing database technology, migrations, and seed behavior."""

    def __init__(self, db_path: str | None = None) -> None:
        """Retain a database path without opening or modifying it."""
        self.db_path = db_path

    @maintenance_errors
    def initialize(self) -> None:
        """Apply the preserved idempotent schema migration sequence."""
        init_db(self.db_path)

    @maintenance_errors
    def seed_defaults(self, *, force: bool, include_projects: bool) -> None:
        """Keep empty-database detection and the existing pre-seed backup policy."""
        seed_default_data_if_empty(self.db_path, force, include_projects=include_projects)

    @maintenance_errors
    def seed_projects(self, request: SeedRequest) -> dict[str, int]:
        """Run the existing bounded project/task generator with explicit options."""
        return seed_database(
            request.projects,
            request.min_tasks,
            request.max_tasks,
            self.db_path,
            request.clean_first,
            request.random_seed,
        )

    @maintenance_errors
    def flush(self, *, flush_all: bool) -> dict[str, int]:
        """Delegate the existing reset, including reference cleanup and sequences."""
        return flush_database(self.db_path, flush_all)

    @maintenance_errors
    def counts(self) -> DatabaseCounts:
        """Read all summary counts in a single query and snapshot."""
        with closing(get_db(self.db_path)) as connection:
            row = connection.execute("""SELECT
                (SELECT COUNT(*) FROM project),
                (SELECT COUNT(*) FROM project_task),
                (SELECT COUNT(*) FROM task_dependencies),
                (SELECT COUNT(*) FROM project_type),
                (SELECT COUNT(*) FROM project_property_value),
                (SELECT COUNT(*) FROM resource_pool)""").fetchone()
        return DatabaseCounts(
            projects=row[0],
            tasks=row[1],
            dependencies=row[2],
            project_types=row[3],
            property_values=row[4],
            pools=row[5],
        )

    @maintenance_errors
    def seed_pool_scenarios(self, *, year: int | None, seed: int, apply: bool) -> PoolSeedReport:
        """Prepare a validated snapshot plan and apply only when explicitly requested."""
        return seed_pool_scenarios(self.db_path, year=year, seed=seed, apply=apply)
