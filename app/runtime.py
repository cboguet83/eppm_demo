"""Process resources owned by the launcher and injected into application services."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import cache
import os
from secrets import token_hex
from threading import Lock

from anyio import CancelScope
from starlette.concurrency import run_in_threadpool

from app.infrastructure.postgresql.authorization import signing_key
from app.infrastructure.postgresql.derived_cache import DerivedCacheState
from app.infrastructure.postgresql.pool import Database
from app.shared.config.database import DatabaseConfig


_creation_lock = Lock()


@cache
def _configured_runtime() -> RuntimeResources:
    """Construct the launcher's closed resource once from process configuration."""
    return RuntimeResources.from_environment(os.environ)


def process_runtime() -> RuntimeResources:
    """Resolve the same launch-owned resource for ASGI and Streamlit reruns.

    Only composition entry points use this provider; services receive the
    resource explicitly. Serialize cache misses so simultaneous callers cannot
    construct multiple pools. Streamlit's user-facing cache clearing does not
    replace the pool owned by the ASGI lifespan. Configuration changes require
    a process restart.
    """
    with _creation_lock:
        return _configured_runtime()


@dataclass(frozen=True)
class RuntimeResources:
    """Share one restricted pool and bounded cache across every request actor.

    The launcher owns the lifetime. Construction performs no database I/O; UI
    reruns receive this resource instead of opening pools or loading credentials.
    The opaque process identity resets presentation state after a restart. Source
    cache tokens independently include the actual database incarnation.
    """

    database: Database = field(repr=False)
    key: bytes = field(repr=False)
    caches: DerivedCacheState = field(default_factory=DerivedCacheState, repr=False)
    identity: str = field(default_factory=lambda: token_hex(16))

    def __post_init__(self) -> None:
        """Reject an invalid signing key before opening the runtime pool."""
        if not isinstance(self.key, bytes) or len(self.key) != 32:
            raise ValueError('Configure a valid PostgreSQL request signing key.')

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> RuntimeResources:
        """Build closed runtime resources without using operator credentials."""
        settings = DatabaseConfig.from_environment(environment)
        key = signing_key(environment.get('DATABASE_CONTEXT_KEY', ''))
        return cls(Database(settings), key)

    @asynccontextmanager
    async def lifespan(self, _application: object) -> AsyncIterator[None]:
        """Check and open on startup; always close outside the ASGI event loop.

        Startup only checks compatibility and runtime privileges. Migrations,
        reference seeds and resets remain explicit operator operations. Shield
        shutdown cleanup so cancellation cannot leave workers/connections open.
        """
        try:
            await run_in_threadpool(self.database.open)
            yield
        finally:
            with CancelScope(shield=True):
                await run_in_threadpool(self.database.close)
