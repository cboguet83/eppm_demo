"""Authorized native cache reads and publication with bounded process memory."""

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
import json
from threading import RLock
from typing import Literal

import psycopg

from app.application.exceptions import PlanningStorageError, ResourcePoolStorageError
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied
from app.domain.resources.models import PoolCapacitySummary
from app.infrastructure.postgresql.authorization import ServerRequestSigner
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import Database
from app.shared.logging import get_logger


type CacheKind = Literal['capacity', 'planning']
type JsonPayload = dict[str, object]
type CacheRow = tuple[int, str, JsonPayload | None, bool, bool]
type MemoryKey = tuple[CacheKind, date, int, str]
logger = get_logger(__name__)
_VERSION = 2


@dataclass(frozen=True)
class CacheRecord:
    """One server-calculated entity with separate small and detailed projections."""

    entity_id: int
    summary: JsonPayload
    detail: JsonPayload


@dataclass(frozen=True)
class MemoryEntry:
    """Immutable bytes prevent caller mutations and permit an exact byte bound."""

    raw: bytes = field(repr=False)
    complete: bool


class DerivedCacheState:
    """Own a bounded LRU; never hold its lock during database I/O or calculation."""

    def __init__(self, *, max_entries: int = 128, max_bytes: int = 32 * 1024 * 1024) -> None:
        """Configure finite per-process storage for injection by composition."""
        if max_entries < 1 or max_bytes < 1:
            raise ValueError('Cache limits must be positive.')
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.lock = RLock()
        self.entries: OrderedDict[MemoryKey, MemoryEntry] = OrderedDict()
        self.size_bytes = 0

    def snapshot(self, kind: CacheKind, day: date, details: bool) -> dict[str, MemoryEntry]:
        """Retain immutable entries locally so concurrent eviction cannot lose a hit."""
        with self.lock:
            return {key[3]: entry for key, entry in self.entries.items()
                    if key[:3] == (kind, day, _VERSION) and (entry.complete or not details)}

    def remember(self, kind: CacheKind, day: date, token: str, payload: JsonPayload, *, complete: bool) -> None:
        """Encode outside the lock, retaining full details over a summary-only hit."""
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(raw) > self.max_bytes:
            return
        key = kind, day, _VERSION, token
        with self.lock:
            previous = self.entries.get(key)
            if previous is not None and previous.complete and not complete:
                self.entries.move_to_end(key)
                return
            if previous is not None:
                self.size_bytes -= len(previous.raw)
            self.entries[key] = MemoryEntry(raw, complete)
            self.entries.move_to_end(key)
            self.size_bytes += len(raw)
            while len(self.entries) > self.max_entries or self.size_bytes > self.max_bytes:
                self.size_bytes -= len(self.entries.popitem(last=False)[1].raw)

    def touch(self, kind: CacheKind, day: date, token: str) -> None:
        """Record a confirmed hit if concurrent eviction has not removed it."""
        with self.lock:
            key = kind, day, _VERSION, token
            if key in self.entries:
                self.entries.move_to_end(key)


class PostgresDerivedCache:
    """Reauthorize reads and reject stale publication before any payload is reused."""

    def __init__(self, database: Database, key: bytes, state: DerivedCacheState, *, access: BusinessAccess) -> None:
        """Inject the shared pool, process memory and trusted request actor."""
        self.database, self.key, self.state, self.access = database, key, state, access

    def _run[Result](self, kind: CacheKind, operation: Callable[[psycopg.Connection], Result], *, write: bool = False) -> Result:
        """Use fresh authorization and complete callback replay for publication."""
        try:
            return run_business(self.database, self.key, self.access, operation, write=write)
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Derived cache operation failed (%s)', type(error).__name__)
            raise self._failure(kind)('Cached data could not be accessed. Please try again.') from None

    @staticmethod
    def _failure(kind: CacheKind) -> type[PlanningStorageError] | type[ResourcePoolStorageError]:
        return PlanningStorageError if kind == 'planning' else ResourcePoolStorageError

    def read(self, kind: CacheKind, selected: list[int] | None, day: date, details: bool,
             known: list[str]) -> list[CacheRow]:
        """Ask the database for current keys and only payloads missing from memory."""
        return self._run(kind, lambda connection: connection.execute(
            'SELECT * FROM eppm.read_derived_cache(%s,%s::bigint[],%s,%s,%s,%s::text[])',
            (kind, selected, day, _VERSION, details, known),
        ).fetchall())

    def publish(self, kind: CacheKind, body: str) -> bool:
        """Freeze payload bytes and sign each complete publication attempt anew."""
        body_hash = sha256(body.encode('utf-8')).hexdigest()
        def operation(connection: psycopg.Connection) -> bool:
            document, signature = ServerRequestSigner(self.key).sign(connection, 'cache.publish', {'body_hash': body_hash})
            return connection.execute('SELECT eppm.publish_derived_cache(%s,%s,%s)', (document, signature, body)).fetchone()[0]
        return self._run(kind, operation, write=True)

    def load(self, kind: CacheKind, selected_ids: list[int] | None, day: date,
             calculate: Callable[[list[int]], list[CacheRecord]], *, details: bool = False) -> list[JsonPayload]:
        """Allow three full calculations, with a fresh authorized read after each.

        JSON is the driver/cache serialization boundary. No database transaction
        or process lock stays open while the injected calculation runs.
        """
        selected = sorted(set(selected_ids)) if selected_ids is not None else None
        try:
            for attempt in range(4):
                remembered = self.state.snapshot(kind, day, details)
                rows = self.read(kind, selected, day, details, list(remembered))
                missing = [row[0] for row in rows if not row[3]]
                if not missing:
                    return self._results(kind, day, details, rows, remembered)
                if attempt == 3:
                    break
                records = calculate(missing)
                if sorted(record.entity_id for record in records) != sorted(missing):
                    raise self._failure(kind)('The cache calculation returned incomplete data.')
                tokens = {row[0]: row[1] for row in rows}
                body = json.dumps({'kind': kind, 'day': day.isoformat(), 'version': _VERSION, 'entries': [
                    {'entity_id': record.entity_id, 'token': tokens[record.entity_id], 'summary': record.summary, 'detail': record.detail}
                    for record in records
                ]}, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
                if self.publish(kind, body):
                    # Reuse the frozen publication body, not caller-owned
                    # dictionaries that could have changed during a retry.
                    for entry in json.loads(body)['entries']:
                        self.state.remember(kind, day, entry['token'], entry['detail'], complete=True)
            raise self._failure(kind)('Data changed repeatedly while calculating; please retry.')
        except AccessDenied:
            raise
        except (KeyError, TypeError, ValueError) as error:
            logger.error('Derived cache payload could not be decoded (%s)', type(error).__name__)
            raise self._failure(kind)('Cached data could not be decoded. Please try again.') from None

    def _results(self, kind: CacheKind, day: date, details: bool, rows: list[CacheRow],
                 remembered: dict[str, MemoryEntry]) -> list[JsonPayload]:
        """Decode independent results, redacting people even for a memory hit."""
        results = []
        for _identity, token, payload, _available, shared in rows:
            if payload is None:
                payload = json.loads(remembered[token].raw)
                self.state.touch(kind, day, token)
            else:
                self.state.remember(kind, day, token, payload, complete=details or kind == 'planning')
            if kind == 'capacity' and not details:
                payload = {name: payload[name] for name in PoolCapacitySummary.__dataclass_fields__}
            elif kind == 'capacity' and not shared:
                payload['contributing_resources'] = []
            results.append(payload)
        return results
