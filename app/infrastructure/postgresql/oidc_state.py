"""Authlib state storage with atomic consumption and no database work on ASGI."""

from collections.abc import Callable
from hashlib import sha256

from psycopg import Connection
from starlette.concurrency import run_in_threadpool

from app.infrastructure.postgresql.authorization import ServerRequestSigner
from app.infrastructure.postgresql.pool import Database


class PostgresOidcState:
    """Keep opaque Authlib state in PostgreSQL, independently of browser cookies."""

    def __init__(self, database: Database, key: bytes, clock: Callable[[], int]) -> None:
        """Inject the shared process pool, server signing key and clock."""
        self.database, self.signer, self.clock = database, ServerRequestSigner(key), clock

    async def set(self, key: str, value: str, expires: int) -> None:
        """Store a request for at most ten minutes on a worker thread."""
        await run_in_threadpool(self._set, key, value, min(expires, 600))

    def _set(self, key: str, value: str, expires: int) -> None:
        state_hash, deadline = sha256(key.encode()).hexdigest(), self.clock() + expires

        def operation(connection: Connection) -> None:
            now = self.clock()
            payload = {"state_hash": state_hash, "value": value,
                       "now": now, "duration": deadline - now}
            proof = self.signer.sign(connection, "oidc.state.store", payload)
            connection.execute("SELECT eppm.oidc_state_store(%s,%s)", proof)
        self.database.run(operation, write=True)

    async def get(self, key: str) -> str | None:
        """Return state once; racing callbacks cannot consume the same request."""
        return await run_in_threadpool(self._consume, key)

    def _consume(self, key: str) -> str | None:
        state_hash = sha256(key.encode()).hexdigest()

        def operation(connection: Connection) -> str | None:
            payload = {"state_hash": state_hash, "now": self.clock()}
            proof = self.signer.sign(connection, "oidc.state.consume", payload)
            return connection.execute("SELECT eppm.oidc_state_consume(%s,%s)", proof).fetchone()[0]
        return self.database.run(operation, write=True)

    async def delete(self, key: str) -> None:
        """Discard remaining state after successful or failed Authlib callbacks."""
        await run_in_threadpool(self._consume, key)
