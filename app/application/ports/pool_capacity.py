"""Boundaries for consistent capacity inputs and derived-data caching."""

from collections.abc import Callable
from datetime import date
from typing import Protocol

from app.domain.resources.inputs import CapacityInputs
from app.domain.resources.models import PoolCapacityDetail, PoolCapacitySummary, ResourcePool

type CapacityCalculation = Callable[[list[int], date], list[PoolCapacityDetail]]
type CapacityResult = list[PoolCapacitySummary] | list[PoolCapacityDetail]


class CapacityReader(Protocol):
    """Read shared organization and allocation data in one snapshot."""

    def read(self, pool_ids: list[int]) -> dict[int, CapacityInputs]: ...

    def pool_hierarchy(self) -> list[ResourcePool]: ...

    def visible_details(self, details: list[PoolCapacityDetail]) -> list[PoolCapacityDetail]: ...


class CapacityCache(Protocol):
    """Reuse calculations while their source revision and day are current."""

    def load(
        self,
        calculate: CapacityCalculation,
        *,
        details: bool = False,
        pool_ids: list[int] | None = None,
    ) -> CapacityResult: ...
