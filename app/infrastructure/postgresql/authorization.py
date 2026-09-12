"""Signed transaction-local actor binding; no credentials or claims reach logs."""

from dataclasses import dataclass, field
import hmac
import json

import psycopg

from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, Actor


def signing_key(value: str) -> bytes:
    """Decode a deployment-managed 256-bit binding key without exposing invalid input."""
    try:
        key = bytes.fromhex(value)
    except (ValueError, TypeError):
        raise ValueError("Configure a valid PostgreSQL request signing key.") from None
    if len(key) != 32:
        raise ValueError("Configure a valid PostgreSQL request signing key.")
    return key


@dataclass(frozen=True)
class ActorBinding:
    """Bind an already server-resolved actor and the injected authorization policy.

    The MAC covers the exact backend and transaction start as well as all policy
    inputs. Changing settings or replaying another transaction's context cannot
    grant privileges. Database checks still read current session/account/grant
    state, including after whole-operation retries.
    """

    access: BusinessAccess
    key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.access.actor, Actor) or len(self.key) != 32:
            raise AccessDenied()

    def __call__(self, connection: psycopg.Connection) -> None:
        """Sign connection-specific context inside its caller-owned transaction."""
        actor, policy = self.access.actor, self.access.policy
        backend, started = connection.execute(
            "SELECT pg_backend_pid(), (extract(epoch FROM transaction_timestamp()) * 1000000)::bigint"
        ).fetchone()
        document = json.dumps({
            "backend": backend, "started": started, "user_id": actor.user_id,
            "session_hash": actor.session_hash, "correlation_id": actor.correlation_id,
            "now": policy.clock(), "idle_seconds": policy.limits.idle_seconds,
            "reauthentication_seconds": policy.limits.reauthentication_seconds,
            "admin_mfa": policy.limits.require_admin_mfa,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        signature = hmac.digest(self.key, document.encode("utf-8"), "sha256").hex()
        try:
            connection.execute("SELECT eppm.bind_actor(%s, %s)", (document, signature))
        except psycopg.errors.InsufficientPrivilege:
            raise AccessDenied() from None


def configure_signing_key(url: str, value: str) -> None:
    """Install the explicit server binding key using separate operator credentials.

    This does not generate or rotate credentials during application startup.
    A changed key invalidates old proofs in subsequent transaction snapshots.
    """
    key = signing_key(value)
    with psycopg.connect(url) as connection:
        connection.execute("""INSERT INTO eppm.request_binding_key(singleton, secret) VALUES (true, %s)
            ON CONFLICT (singleton) DO UPDATE SET secret=excluded.secret""", (key,))
