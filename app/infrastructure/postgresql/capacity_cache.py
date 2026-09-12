"""Native capacity cache adapter preserving the existing service projections."""

from collections.abc import Callable
from dataclasses import asdict, fields
from datetime import date

from app.application.exceptions import ResourcePoolStorageError
from app.application.ports.pool_capacity import CapacityCalculation, CapacityResult
from app.application.services.business_access import BusinessAccess
from app.domain.resources.models import DailyOverassignment, PoolCapacityDetail, PoolCapacitySummary, PoolResourceContribution
from app.infrastructure.postgresql.derived_cache import CacheRecord, DerivedCacheState, JsonPayload, PostgresDerivedCache
from app.infrastructure.postgresql.pool import Database


class PostgresCapacityCache:
    """Keep capacity calculations outside transactions and publish only current data."""

    def __init__(self, database: Database, key: bytes, state: DerivedCacheState, today: Callable[[], date],
                 *, access: BusinessAccess) -> None:
        """Inject one process cache state and the effective capacity-day clock."""
        self.cache = PostgresDerivedCache(database, key, state, access=access)
        self.today = today

    def load(self, calculate: CapacityCalculation, *, details: bool = False,
             pool_ids: list[int] | None = None) -> CapacityResult:
        """Return matching summaries/details without discarding full memory entries."""
        day = self.today()
        def operation(selected: list[int]) -> list[CacheRecord]:
            records = []
            for detail in calculate(selected, day):
                payload = asdict(detail)
                summary = {item.name: payload[item.name] for item in fields(PoolCapacitySummary)}
                records.append(CacheRecord(detail.pool_id, summary, payload))
            return records
        rows = self.cache.load('capacity', pool_ids, day, operation, details=details)
        try:
            return [_detail(row) for row in rows] if details else [PoolCapacitySummary(**row) for row in rows]
        except (KeyError, TypeError, ValueError):
            raise ResourcePoolStorageError('Cached capacity data could not be decoded. Please try again.') from None


def _detail(payload: JsonPayload) -> PoolCapacityDetail:
    """Reconstruct nested domain records at the JSON boundary without sharing them."""
    return PoolCapacityDetail(**(payload | {
        'contributing_resources': [PoolResourceContribution(**row) for row in payload['contributing_resources']],
        'daily_overassignments': [DailyOverassignment(**row) for row in payload['daily_overassignments']],
    }))
