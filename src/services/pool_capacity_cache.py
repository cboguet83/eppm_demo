"""Compatibility exports for callers awaiting the planning migration."""

from datetime import date

from app.main import capacity_cache_state, create_pool_capacity_cache, create_pool_capacity_service
from app.application.ports.pool_capacity import CapacityResult
from app.domain.resources.models import PoolCapacityDetail, PoolCapacitySummary
from app.infrastructure.database.pool_capacity_cache import install_capacity_cache

_MEMORY = capacity_cache_state().entries
_LOCK = capacity_cache_state().lock
_VERSION = 1


def _batch_calculate(
    db_path: str | None,
    pool_ids: list[int],
    on_date: date | None = None,
) -> list[PoolCapacityDetail]:
    """Delegate legacy cache misses to the typed, consistent input reader."""
    return create_pool_capacity_service(db_path).calculate_many(pool_ids, on_date)


def load_pool_capacities(
    db_path: str | None = None,
    *,
    details: bool = False,
    pool_ids: list[int] | None = None,
) -> CapacityResult:
    """Keep the existing call shape and cache-miss seam for planning callers."""
    return create_pool_capacity_cache(db_path).load(
        lambda ids, day: _batch_calculate(db_path, ids, on_date=day),
        details=details,
        pool_ids=pool_ids,
    )
