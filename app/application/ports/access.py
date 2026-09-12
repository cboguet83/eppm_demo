"""Persistence contract for identity, sessions, grants, and their atomic audit."""

from collections.abc import Callable
from typing import Protocol, TypedDict

from app.domain.access.models import Actor, ProjectScope, VerifiedIdentity


class UserRecord(TypedDict):
    """Safe user profile for access administration and the account status screen."""

    id: int
    status: str
    email: str
    display_name: str
    created_at: int
    updated_at: int


class SessionRecord(TypedDict):
    """Persisted server-side session timing and revocation state."""

    user_id: int
    status: str
    auth_time: int
    expires_at: int
    last_activity: int
    mfa: bool
    revoked: bool


class AssignmentRecord(TypedDict):
    """Fixed role plus the scope belonging to that same grant."""

    id: int
    user_id: int
    role: str
    scope_json: str
    invalid_reason: str
    created_at: int
    created_by: str


class AccessStore(Protocol):
    """All methods operate on the caller's single transaction."""

    def find_user(self, user_id: int) -> UserRecord | None: ...
    def list_users(self, search: str, limit: int = 100, *, after_id: int = 0,
                   status: str | None = None) -> list[UserRecord]: ...
    def assignments(self, user_id: int) -> list[AssignmentRecord]: ...
    def assignment(self, assignment_id: int) -> AssignmentRecord | None: ...
    def security_revision(self) -> int: ...
    def session(self, session_hash: str) -> SessionRecord | None: ...
    def scope_projects(self, scope: ProjectScope) -> set[int]: ...
    def scope_catalog(self) -> list[dict[str, object]]: ...
    def scope_project_choices(self, search: str) -> list[dict[str, object]]: ...
    def list_audit(self, limit: int = 100) -> list[dict[str, object]]: ...
    def record_sign_in(self, identity: VerifiedIdentity, configured_issuer: str, session_hash: str,
                       previous_hash: str | None, now: int, expires_at: int, correlation: str) -> None: ...
    def register_account(self, issuer: str, subject: str, display_name: str, actor: Actor, now: int) -> int: ...
    def change_status(self, user_id: int, status: str, actor: Actor, now: int) -> None: ...
    def assign_role(self, user_id: int, role: str, scope: ProjectScope, actor: Actor, now: int) -> int: ...
    def remove_assignment(self, assignment_id: int, actor: Actor, now: int) -> None: ...
    def end_session(self, actor: Actor, now: int) -> None: ...
    def record_activity(self, actor: Actor, now: int, expires_at: int) -> None: ...


class AccessGateway(Protocol):
    """Replay complete authorized operations; each mutation includes required audit."""

    def run[Result](self, operation: Callable[[AccessStore], Result], *, write: bool = False,
                    actor: Actor | None = None) -> Result: ...


class DeploymentAccessStore(Protocol):
    """Explicit deployment operations, never an ordinary actor's implicit fallback."""

    def list_users(self, search: str, limit: int = 100, *, after_id: int = 0,
                   status: str | None = None) -> list[UserRecord]: ...
    def appoint_administrator(self, user_id: int, operator: str, correlation: str, now: int,
                              reason: str, *, initial: bool) -> None: ...


class DeploymentAccessGateway(Protocol):
    """Use separate operator credentials and complete, auditable callbacks."""

    def run[Result](self, operation: Callable[[DeploymentAccessStore], Result], *, write: bool = False) -> Result: ...
