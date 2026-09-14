"""Capacity use cases with injected persistence, cache, and calendar day."""

from collections.abc import Callable
from datetime import date
from typing import cast

from app.application.ports.pool_capacity import CapacityCache, CapacityReader
from app.domain.resources.capacity import calculate_capacity
from app.domain.resources.allocation_scope import scope_pool_detail
from app.domain.resources.models import PoolCapacityDetail, PoolCapacitySummary


class PoolCapacityService:
    """Calculate pure capacity models from a consistent shared input snapshot."""

    def __init__(
        self,
        reader: CapacityReader,
        cache: CapacityCache,
        today: Callable[[], date],
    ) -> None:
        """Inject the snapshot reader, derived-data cache, and effective-day clock."""
        self._reader = reader
        self._cache = cache
        self._today = today

    def calculate_many(
        self,
        pool_ids: list[int],
        on_date: date | None = None,
    ) -> list[PoolCapacityDetail]:
        """Read all requested inputs once and evaluate on the same day."""
        pool_ids = list(pool_ids)
        day = on_date if on_date is not None else self._today()
        inputs = self._reader.read(pool_ids)
        return self._reader.visible_details(
            [calculate_capacity(inputs[pool_id], day) for pool_id in pool_ids]
        )

    def get_summaries(self, pool_ids: list[int] | None = None) -> list[PoolCapacitySummary]:
        """Return revision-checked summary cards without decoding full details."""
        return cast(
            list[PoolCapacitySummary],
            self._cache.load(
                self.calculate_many,
                pool_ids=pool_ids,
            ),
        )

    def get_details(self, pool_ids: list[int], *, project_ids: set[int] | None = None) -> list[PoolCapacityDetail]:
        """Return full details only for explicitly requested pools."""
        details = cast(
            list[PoolCapacityDetail],
            self._cache.load(
                self.calculate_many,
                details=True,
                pool_ids=pool_ids,
            ),
        )
        return details if project_ids is None else [scope_pool_detail(detail, project_ids) for detail in details]
