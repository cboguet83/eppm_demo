"""Complete native maintenance port with separate operator credentials and archives."""

from collections.abc import Callable
from functools import wraps
from pathlib import Path

import psycopg

from app.application.exceptions import DatabaseMaintenanceError
from app.application.ports.maintenance import (
    AllocationSeedReport, DatabaseCounts, PoolSeedReport, SeedRequest,
)
from app.domain.resources.allocation_generation import AllocationGenerationRequest
from app.infrastructure.postgresql import maintenance
from app.infrastructure.postgresql.backup import PostgresBackup, PostgresTools
from app.infrastructure.postgresql.errors import (
    DatabaseUnavailableError, MigrationError, SchemaCompatibilityError,
    TransactionRetryError,
)
from app.infrastructure.postgresql.migration import migrate
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.shared.logging import get_logger


logger = get_logger(__name__)


def maintenance_errors[**P, Result](operation: Callable[P, Result]) -> Callable[P, Result]:
    """Translate storage/lifecycle errors while retaining safe validation errors."""
    @wraps(operation)
    def run(*args: P.args, **kwargs: P.kwargs) -> Result:
        try:
            return operation(*args, **kwargs)
        except (psycopg.Error, DatabaseUnavailableError, MigrationError,
                SchemaCompatibilityError, TransactionRetryError, OSError) as error:
            logger.error('PostgreSQL maintenance failed (%s)', type(error).__name__)
            raise DatabaseMaintenanceError(
                'Database maintenance could not complete. '
                'Any pre-operation backup is retained.',
            ) from None
    return run


class PostgresMaintenanceGateway:
    """Implement operator initialization, all generators, resets and summary reads."""

    def __init__(
        self, url: str, backup_directory: Path, *,
        archive_tools: PostgresTools | None = None,
        default_seed_year: int | None = None,
    ) -> None:
        """Construct separate operator resources without accessing the database."""
        self.database = OperatorDatabase(url)
        self.backup = PostgresBackup(url, backup_directory, tools=archive_tools)
        self._url = url
        self._default_seed_year = default_seed_year

    @maintenance_errors
    def initialize(self) -> None:
        """Explicitly migrate and install initial references for deployment tools."""
        migrate(self._url)
        self.database.run(ensure_reference_catalog, write=True)

    @maintenance_errors
    def seed_defaults(self, *, force: bool, include_projects: bool) -> None:
        """Preserve populated catalogs unless a backed-up replacement was requested."""
        maintenance.seed_defaults(
            self.database, self.backup, force=force,
            include_projects=include_projects, year=self._default_seed_year,
        )

    @maintenance_errors
    def seed_projects(self, request: SeedRequest) -> dict[str, int]:
        """Generate validated projects, typed properties and native schedules."""
        return maintenance.seed_projects(self.database, self.backup, request)

    @maintenance_errors
    def flush(self, *, flush_all: bool) -> dict[str, int]:
        """Apply the backed-up project-only or full reference cleanup."""
        return maintenance.reset_database(self.database, self.backup, flush_all=flush_all)

    @maintenance_errors
    def counts(self) -> DatabaseCounts:
        """Read all navigation/maintenance counts in one repeatable-read snapshot."""
        return maintenance.counts(self.database)

    @maintenance_errors
    def clear_pool_allocations(self) -> int:
        """Archive and delete demand while retaining staffing mappings."""
        return maintenance.clear_pool_allocations(self.database, self.backup)

    @maintenance_errors
    def generate_pool_allocations(
        self, request: AllocationGenerationRequest, *, apply: bool,
        expected_fingerprint: str | None,
    ) -> AllocationSeedReport:
        """Simulate or apply the requested capacity mix against reviewed sources."""
        return maintenance.generate_pool_allocations(
            self.database, self.backup, request,
            apply=apply, expected_fingerprint=expected_fingerprint,
        )

    @maintenance_errors
    def seed_pool_scenarios(
        self, *, year: int | None, seed: int, apply: bool,
    ) -> PoolSeedReport:
        """Preview or apply additive hierarchy scenarios using one archive."""
        return maintenance.seed_pool_scenarios(
            self.database, self.backup, year=year, seed=seed, apply=apply,
        )
