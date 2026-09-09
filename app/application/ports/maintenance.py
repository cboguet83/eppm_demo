"""Startup and maintenance contracts independent of configuration and SQLite."""

from dataclasses import dataclass
from typing import NotRequired, Protocol, TypedDict
from app.domain.resources.allocation_generation import AllocationGenerationRequest


class AllocationPreviewRow(TypedDict):
    """One pool's generated usage and staffing in a seed preview."""

    pool_id: int
    pool_name: str
    allocation_pct: float
    target_allocation_pct: float
    maximum_allocation_pct: float
    unstaffed: bool
    capacity_fte: float


class AllocationSeedReport(TypedDict):
    """Validated distribution, changes, and source identity for explicit application."""

    fingerprint: str
    applied: bool
    total_pools: int
    allocated_pools: int
    overallocated_pools: int
    underallocated_pools: int
    fully_allocated_pools: int
    unstaffed_pools: int
    average_allocation_pct: float
    assignments_removed: int
    assignments_created: int
    mappings_removed: int
    mappings_created: int
    capacity_limits_initialized: int
    rows: list[AllocationPreviewRow]


class PoolScenario(TypedDict):
    """One generated pool's staffing scenario in the preview report."""

    role: str
    pool_id: int
    theoretical_fte: float
    normal_assigned_fte: float


class ParentSummary(TypedDict):
    """Counts of generated groups and pools beneath a service root."""

    parent: str
    new_groups: int
    new_pools: int


class PoolSeedReport(TypedDict):
    """Preview/application outcome of an additive pool scenario installation."""

    new_groups: int
    new_pools: int
    applied: NotRequired[bool]
    already_seeded: NotRequired[bool]
    parents: NotRequired[list[ParentSummary]]
    new_employee_mappings: NotRequired[int]
    new_project_assignments: NotRequired[int]
    new_task_assignments: NotRequired[int]
    scenarios: NotRequired[list[PoolScenario]]
    existing_foreign_key_violations: NotRequired[int]


class DatabaseCounts(TypedDict):
    """Persisted counts used by the startup and navigation summaries."""

    projects: int
    tasks: int
    dependencies: int
    project_types: int
    property_values: int
    pools: int


@dataclass(frozen=True)
class SeedRequest:
    """Explicit options for the existing project and schedule generator."""

    projects: int = 1000
    min_tasks: int = 0
    max_tasks: int = 15
    clean_first: bool = True
    random_seed: int | None = 42


class MaintenanceGateway(Protocol):
    """Infrastructure operations used by startup and explicit maintenance."""

    def initialize(self) -> None: ...
    def seed_defaults(self, *, force: bool, include_projects: bool) -> None: ...
    def seed_projects(self, request: SeedRequest) -> dict[str, int]: ...
    def flush(self, *, flush_all: bool) -> dict[str, int]: ...
    def counts(self) -> DatabaseCounts: ...
    def clear_pool_allocations(self) -> int: ...
    def generate_pool_allocations(
        self, request: AllocationGenerationRequest, *, apply: bool, expected_fingerprint: str | None,
    ) -> AllocationSeedReport: ...
    def seed_pool_scenarios(
        self, *, year: int | None, seed: int, apply: bool
    ) -> PoolSeedReport: ...
