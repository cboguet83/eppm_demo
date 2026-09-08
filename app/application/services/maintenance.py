"""Explicit database startup, demo generation, and maintenance use cases."""

from app.application.ports.maintenance import (
    DatabaseCounts,
    MaintenanceGateway,
    PoolSeedReport,
    SeedRequest,
)


class MaintenanceService:
    """Coordinate startup policy with injected infrastructure operations."""

    def __init__(self, gateway: MaintenanceGateway) -> None:
        """Inject initialization, backup-aware seeding, and count reads."""
        self._gateway = gateway

    def startup(self, *, force: bool = False, projects: int = 0) -> None:
        """Initialize schema and preserve ordinary-versus-forced startup behavior."""
        if type(projects) is not int or projects < 0:
            raise ValueError("Invalid project count.")
        self._gateway.initialize()
        if force and projects > 0:
            self.seed_projects(SeedRequest(projects=projects))
        else:
            self.seed_defaults(force=force)

    def seed_defaults(self, *, force: bool = False, include_projects: bool = True) -> None:
        """Install the existing default catalog, preserving populated user catalogs."""
        self._gateway.seed_defaults(force=force, include_projects=include_projects)

    def seed_projects(self, request: SeedRequest) -> dict[str, int]:
        """Validate generation limits before requesting a backed-up seed operation."""
        counts = (request.projects, request.min_tasks, request.max_tasks)
        if any(type(value) is not int for value in counts) or (
            request.projects < 0
            or request.min_tasks < 0
            or request.max_tasks < request.min_tasks
            or request.max_tasks > 50
        ):
            raise ValueError("Invalid project or task count.")
        return self._gateway.seed_projects(request)

    def flush(self, *, flush_all: bool = False) -> dict[str, int]:
        """Apply an explicitly requested project-only or full-reference reset."""
        return self._gateway.flush(flush_all=flush_all)

    def counts(self) -> DatabaseCounts:
        """Read navigation and post-seed counts without loading project records."""
        return self._gateway.counts()

    def seed_pool_scenarios(
        self, *, year: int | None = None, seed: int = 20260908, apply: bool = False
    ) -> PoolSeedReport:
        """Preview or explicitly apply the existing additive pool scenario plan."""
        if year is not None and (type(year) is not int or not 1 <= year <= 9999):
            raise ValueError("Invalid scenario year.")
        if type(seed) is not int:
            raise ValueError("Invalid scenario random seed.")
        return self._gateway.seed_pool_scenarios(year=year, seed=seed, apply=apply)
