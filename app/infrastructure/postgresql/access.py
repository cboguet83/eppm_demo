"""PostgreSQL access adapters with complete audited mutations and actor binding."""

from collections.abc import Callable, Sequence
from dataclasses import asdict
from typing import cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.application.ports.access import AccessStore, AssignmentRecord, DeploymentAccessStore, SessionRecord, UserRecord
from app.application.services.access import AuthorizationPolicy
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, AccessStorageError, Actor, ProjectScope, ReauthenticationRequired, VerifiedIdentity
from app.infrastructure.postgresql.authorization import ActorBinding, ServerRequestSigner
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.migration import check_schema
from app.infrastructure.postgresql.pool import Database, OperatorDatabase


_SAFE_VALIDATION = {
    "At least one active access administrator must remain": "At least one active access administrator must remain.",
    "Initial access setup is already complete; use explicit recovery": "Initial access setup is already complete. Use explicit recovery if needed.",
    "Select an existing account with a verified OIDC login": "Select an existing account with a verified OIDC login.",
    "Revoke the invalid assignment before granting its replacement": "Revoke the invalid assignment before granting its replacement.",
}


def access_operation[Result](operation: Callable[[], Result]) -> Result:
    """Translate only after rollback/replay; never expose PostgreSQL diagnostics."""
    try:
        return operation()
    except psycopg.errors.InsufficientPrivilege as error:
        if error.diag.message_primary == "Sign in again before changing application access":
            raise ReauthenticationRequired("Sign in again before changing application access.") from None
        raise AccessDenied() from None
    except psycopg.errors.InvalidParameterValue as error:
        raise ValueError(_SAFE_VALIDATION.get(error.diag.message_primary, "Invalid application access request.")) from None
    except psycopg.errors.UniqueViolation:
        raise ValueError("That identity or assignment already exists.") from None
    except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError):
        raise AccessStorageError("Access storage is unavailable. The operation could not be completed.") from None


class _AccessRows:
    """Shared explicit profile queries; native RLS remains authoritative."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def _rows(self, query: str, parameters: Sequence[object] = ()) -> list[dict[str, object]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return cast(list[dict[str, object]], cursor.execute(query, parameters).fetchall())

    def find_user(self, user_id: int) -> UserRecord | None:
        """Read a safe profile through the current actor's row policy."""
        rows = self._rows("SELECT id,status,email,display_name,created_at,updated_at FROM eppm.app_user WHERE id=%s", (user_id,))
        return cast(UserRecord, rows[0]) if rows else None

    def list_users(self, search: str, limit: int = 100, *, after_id: int = 0,
                   status: str | None = None) -> list[UserRecord]:
        """Apply status/search/continuation before the bounded result limit."""
        rows = self._rows("""SELECT id,status,email,display_name,created_at,updated_at FROM eppm.app_user
            WHERE id>%s AND (%s::text IS NULL OR status=%s) AND
            (position(lower(%s) IN lower(display_name))>0 OR position(lower(%s) IN lower(email))>0 OR id::text=%s)
            ORDER BY id LIMIT %s""", (after_id, status, status, search, search, search, min(max(limit, 1), 200)))
        return cast(list[UserRecord], rows)


class PostgresAccessStore(_AccessRows):
    """One transaction's typed reads and inseparable security mutation/audit calls."""

    def __init__(self, connection: psycopg.Connection, signer: ServerRequestSigner,
                 policy: AuthorizationPolicy, actor: Actor | None, *, writable: bool) -> None:
        """Keep trusted context local to this transaction and retry attempt."""
        super().__init__(connection)
        self.signer, self.policy, self.actor, self.writable = signer, policy, actor, writable
        self._lookup: tuple[str, dict[str, object] | None] | None = None

    def _refresh(self, actor: Actor, now: int) -> None:
        if not self.writable or actor != self.actor:
            raise AccessDenied()
        # Refresh the trusted clock immediately before a complete mutation.
        access = BusinessAccess(actor, AuthorizationPolicy(lambda: now, self.policy.limits))
        ActorBinding(access, self.signer.key)(self.connection)

    def assignments(self, user_id: int) -> list[AssignmentRecord]:
        """Return current self/admin grants with the existing JSON-text DTO contract."""
        return cast(list[AssignmentRecord], self._rows("""SELECT id,user_id,role,scope_json::text AS scope_json,
            invalid_reason,created_at,created_by FROM eppm.app_role_assignment WHERE user_id=%s ORDER BY id""", (user_id,)))

    def assignment(self, assignment_id: int) -> AssignmentRecord | None:
        """Read one visible assignment without exposing other users' grants."""
        rows = self._rows("""SELECT id,user_id,role,scope_json::text AS scope_json,invalid_reason,created_at,created_by
            FROM eppm.app_role_assignment WHERE id=%s""", (assignment_id,))
        return cast(AssignmentRecord, rows[0]) if rows else None

    def session(self, session_hash: str) -> SessionRecord | None:
        """Read only the bound actor, or a specifically signed cookie lookup."""
        if self.actor is not None:
            if session_hash != self.actor.session_hash:
                return None
            context = self.connection.execute("SELECT eppm.current_actor(false)").fetchone()[0]
            return SessionRecord(user_id=context["user_id"], status=context["status"],
                                 auth_time=context["auth_time"], expires_at=context["expires_at"],
                                 last_activity=context["last_activity"], mfa=context["mfa"], revoked=False)
        if self._lookup is None or self._lookup[0] != session_hash:
            proof = self.signer.sign(self.connection, "session.lookup", {"session_hash": session_hash})
            self._lookup = (session_hash, self.connection.execute("SELECT eppm.session_lookup(%s,%s)", proof).fetchone()[0])
        return cast(SessionRecord, self._lookup[1]["session"]) if self._lookup[1] else None

    def security_revision(self) -> int:
        """Read account revision in the same snapshot as the validated session."""
        if self.actor is not None:
            return self.connection.execute("SELECT eppm.access_security_revision()").fetchone()[0]
        if self._lookup is None or self._lookup[1] is None:
            raise AccessDenied()
        return cast(int, self._lookup[1]["security_revision"])

    def scope_projects(self, scope: ProjectScope) -> set[int]:
        """Evaluate a persisted actor grant through a purpose-specific server proof."""
        if self.actor is None:
            raise AccessDenied()
        proof = self.signer.sign(self.connection, "policy.scope", {"user_id": self.actor.user_id, "scope": scope.to_dict()})
        resolved = self.connection.execute("SELECT eppm.policy_scope_projects(%s,%s)", proof).fetchone()[0]
        if resolved is None:
            raise ValueError("Scope contains a missing or unsupported reference.")
        return set(resolved)

    def scope_catalog(self) -> list[dict[str, object]]:
        """Read only categorical references through the administrator interface."""
        return self.connection.execute("SELECT eppm.admin_scope_catalog()").fetchone()[0]

    def scope_project_choices(self, search: str) -> list[dict[str, object]]:
        """Read bounded ID/name choices without granting portfolio access."""
        return self._rows("SELECT id,name FROM eppm.admin_project_choices(%s)", (search,))

    def list_audit(self, limit: int = 100) -> list[dict[str, object]]:
        """Read bounded immutable audit with its existing JSON-text DTO boundary."""
        return self._rows("""SELECT id,occurred_at,actor,target,action,outcome,correlation_id,
            details_json::text AS details_json FROM eppm.app_security_audit ORDER BY id DESC LIMIT %s""", (min(max(limit, 1), 500),))

    def record_sign_in(self, identity: VerifiedIdentity, configured_issuer: str, session_hash: str,
                       previous_hash: str | None, now: int, expires_at: int, correlation: str) -> None:
        """Persist only a server-verified identity, session rotation and mandatory audit."""
        if not self.writable or self.actor is not None:
            raise AccessDenied()
        proof = self.signer.sign(self.connection, "session.sign_in", {
            "identity": asdict(identity), "configured_issuer": configured_issuer, "session_hash": session_hash,
            "previous_hash": previous_hash, "now": now, "expires_at": expires_at, "correlation_id": correlation,
        })
        self.connection.execute("SELECT eppm.authenticate_identity(%s,%s)", proof)

    def register_account(self, issuer: str, subject: str, display_name: str, actor: Actor, now: int) -> int:
        """Register and audit through the native access-administrator boundary."""
        self._refresh(actor, now)
        return self.connection.execute("SELECT eppm.admin_register(%s,%s,%s)", (issuer, subject, display_name)).fetchone()[0]

    def change_status(self, user_id: int, status: str, actor: Actor, now: int) -> None:
        """Change status with native administrator continuity and mandatory audit."""
        self._refresh(actor, now)
        self.connection.execute("SELECT eppm.admin_set_status(%s,%s)", (user_id, status))

    def assign_role(self, user_id: int, role: str, scope: ProjectScope, actor: Actor, now: int) -> int:
        """Grant one canonical permission-bearing scope with its required audit."""
        self._refresh(actor, now)
        return self.connection.execute("SELECT eppm.admin_grant(%s,%s,%s)", (user_id, role, Jsonb(scope.to_dict()))).fetchone()[0]

    def remove_assignment(self, assignment_id: int, actor: Actor, now: int) -> None:
        """Revoke without allowing the last active administrator to disappear."""
        self._refresh(actor, now)
        self.connection.execute("SELECT eppm.admin_revoke(%s)", (assignment_id,))

    def end_session(self, actor: Actor, now: int) -> None:
        """Revoke and audit the current session without global invalidation."""
        self._refresh(actor, now)
        self.connection.execute("SELECT eppm.session_logout()")

    def record_activity(self, actor: Actor, now: int, expires_at: int) -> None:
        """Touch only the actor's activity, preserving provider authentication time."""
        if expires_at != now + self.policy.limits.idle_seconds:
            raise AccessDenied()
        self._refresh(actor, now)
        self.connection.execute("SELECT eppm.session_activity()")


class PostgresAccessGateway:
    """Use the process pool and bind an actor again before every callback attempt."""

    def __init__(self, database: Database, key: bytes, policy: AuthorizationPolicy) -> None:
        """Inject one shared pool, the deployment signing key and explicit policy."""
        self.database, self.signer, self.policy = database, ServerRequestSigner(key), policy

    def run[Result](self, operation: Callable[[AccessStore], Result], *, write: bool = False,
                    actor: Actor | None = None) -> Result:
        """Return after commit; never replay token exchange or other external effects."""
        bind = ActorBinding(BusinessAccess(actor, self.policy), self.signer.key) if actor else None
        def callback(connection: psycopg.Connection) -> Result:
            return operation(PostgresAccessStore(connection, self.signer, self.policy, actor, writable=write))
        return access_operation(lambda: self.database.run(callback, write=write, bind=bind))


class PostgresDeploymentAccessStore(_AccessRows):
    """Operator-only profile inspection and atomic bootstrap/recovery."""

    def appoint_administrator(self, user_id: int, operator: str, correlation: str, now: int,
                              reason: str, *, initial: bool) -> None:
        """Appoint an explicitly verified account and require a complete audit."""
        self.connection.execute("SELECT eppm.operator_appoint_admin(%s,%s,%s,%s,%s,%s)",
                                (user_id, operator, correlation, now, reason, initial))


class PostgresDeploymentAccessGateway:
    """Separate operator connections cannot be supplied by an ordinary actor."""

    def __init__(self, database: OperatorDatabase) -> None:
        """Inject an explicit deployment connection source, never a runtime fallback."""
        self.database = database

    def run[Result](self, operation: Callable[[DeploymentAccessStore], Result], *, write: bool = False) -> Result:
        """Check compatibility and replay the full operator operation when required."""
        def callback(connection: psycopg.Connection) -> Result:
            check_schema(connection)
            return operation(PostgresDeploymentAccessStore(connection))
        return access_operation(lambda: self.database.run(callback, write=write))
