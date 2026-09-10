"""Short-lived, single-use OIDC state for Authlib's server-side cache interface."""

from collections.abc import Callable
from contextlib import closing
from hashlib import sha256

from starlette.concurrency import run_in_threadpool

from app.infrastructure.database.connection import get_db


class SqliteOidcState:
    """Keep PKCE verifiers out of cookies and consume state atomically across workers."""

    def __init__(self, db_path: str, clock: Callable[[], int]) -> None:
        self.db_path, self.clock = db_path, clock

    async def set(self, key: str, value: str, expires: int) -> None:
        """Persist Authlib state for at most ten minutes, pruning expired requests."""
        await run_in_threadpool(self._set, key, value, min(expires, 600))

    def _set(self, key: str, value: str, expires: int) -> None:
        with closing(get_db(self.db_path)) as conn, conn:
            conn.execute("DELETE FROM app_oidc_state WHERE expires_at<=?", (self.clock(),))
            conn.execute("INSERT INTO app_oidc_state(state_hash,data,expires_at) VALUES (?,?,?)",
                         (sha256(key.encode()).hexdigest(), value, self.clock() + expires))

    async def get(self, key: str) -> str | None:
        """Read and delete in one SQL statement so concurrent callbacks cannot replay."""
        return await run_in_threadpool(self._consume, key)

    def _consume(self, key: str) -> str | None:
        with closing(get_db(self.db_path)) as conn, conn:
            row = conn.execute("DELETE FROM app_oidc_state WHERE state_hash=? RETURNING data,expires_at",
                               (sha256(key.encode()).hexdigest(),)).fetchone()
            return row[0] if row is not None and row[1] > self.clock() else None

    async def delete(self, key: str) -> None:
        """Discard state after Authlib's callback, including failed requests."""
        await run_in_threadpool(self._consume, key)
