"""Current-session authorization and transactional access administration."""

from collections.abc import Callable, Collection
from dataclasses import dataclass
import hashlib
import json

from app.application.ports.access import AccessGateway, AccessStore, AssignmentRecord, SessionRecord, UserRecord
from app.domain.access.models import (
    APPLICATION_ROLES, ROLE_PERMISSIONS, USER_STATES, AccessDenied, Actor,
    Permission, ProjectScope, ReauthenticationRequired, VerifiedIdentity,
    normalize_scope, validate_assignment,
)


@dataclass(frozen=True)
class SessionLimits:
    """Explicit project defaults; provider token expiry may shorten the session."""

    idle_seconds: int = 900
    absolute_seconds: int = 28800
    reauthentication_seconds: int = 300
    require_admin_mfa: bool = False

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in
               (self.idle_seconds, self.absolute_seconds, self.reauthentication_seconds)):
            raise ValueError("Session limits must be positive integer seconds.")


class AuthorizationPolicy:
    """Positive grants with permission and scope checked on the same assignment."""

    def __init__(self, clock: Callable[[], int], limits: SessionLimits) -> None:
        self.clock, self.limits = clock, limits

    def session(self, store: AccessStore, actor: Actor, *, active: bool = True) -> SessionRecord:
        """Validate current session and account state without extending activity."""
        session = store.session(actor.session_hash)
        now = self.clock()
        if (session is None or session["user_id"] != actor.user_id or session["revoked"]
                or now >= session["expires_at"] or now >= session["auth_time"] + self.limits.absolute_seconds
                or now - session["last_activity"] >= self.limits.idle_seconds
                or session["auth_time"] > now + 30 or (active and session["status"] != "active")):
            raise AccessDenied()
        return session

    def grants(self, store: AccessStore, actor: Actor, permission: Permission) -> list[tuple[AssignmentRecord, ProjectScope]]:
        """Ignore corrupt grants; invalid authorization data can never add access."""
        session = self.session(store, actor)
        result = []
        for assignment in store.assignments(actor.user_id):
            if assignment["invalid_reason"]:
                continue
            if permission not in ROLE_PERMISSIONS.get(assignment["role"], frozenset()):
                continue
            if assignment["role"] in APPLICATION_ROLES and self.limits.require_admin_mfa and not session["mfa"]:
                continue
            try:
                scope = normalize_scope(json.loads(assignment["scope_json"]))
                validate_assignment(assignment["role"], scope)
            except (ValueError, TypeError):
                continue
            result.append((assignment, scope))
        return result

    def projects(self, store: AccessStore, actor: Actor, permission: Permission = Permission.READ) -> set[int]:
        """Union independently valid permission-bearing scopes using current data."""
        allowed: set[int] = set()
        for _, scope in self.grants(store, actor, permission):
            try:
                allowed.update(store.scope_projects(scope))
            except ValueError:
                continue
        return allowed

    def require(self, store: AccessStore, actor: Actor, permission: Permission,
                project_ids: Collection[int] | None = None, *, recent: bool = False) -> None:
        """Check all affected projects or an explicit application-wide grant."""
        session = self.session(store, actor)
        if project_ids is None:
            permitted = any(scope.kind == "all" for _, scope in self.grants(store, actor, permission))
        else:
            permitted = bool(project_ids) and set(project_ids) <= self.projects(store, actor, permission)
        if not permitted:
            raise AccessDenied()
        if recent and self.clock() - session["auth_time"] >= self.limits.reauthentication_seconds:
            raise ReauthenticationRequired("Sign in again before changing application access.")


def _safe_text(value: str, maximum: int, *, required: bool = False) -> str:
    """Bound audit/profile fields and reject control characters rather than log them."""
    if not isinstance(value, str) or len(value) > maximum or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Invalid text value.")
    if required and not value.strip():
        raise ValueError("A nonempty value is required.")
    return value


def session_digest(cookie: str) -> str:
    """Hash a high-entropy opaque cookie before lookup or persistence."""
    if not isinstance(cookie, str) or not 32 <= len(cookie) <= 256:
        raise AccessDenied()
    return hashlib.sha256(cookie.encode("utf-8")).hexdigest()


class AccessService:
    """Resolve identities and administer fixed assignments with mandatory audit."""

    def __init__(self, gateway: AccessGateway, policy: AuthorizationPolicy, issuer: str,
                 token_factory: Callable[[], str]) -> None:
        self.gateway, self.policy, self.issuer = gateway, policy, issuer
        self.token_factory = token_factory

    def sign_in(self, identity: VerifiedIdentity, previous_cookie: str | None = None) -> str:
        """Accept only verified configured-provider identities and rotate the browser session."""
        now = self.policy.clock()
        if identity.issuer != self.issuer or identity.expires_at <= now or identity.auth_time > now + 30:
            raise AccessDenied()
        _safe_text(identity.subject, 512, required=True)
        _safe_text(identity.email, 320)
        _safe_text(identity.display_name, 256)
        expiry = min(identity.expires_at, identity.auth_time + self.policy.limits.absolute_seconds)
        if expiry <= now:
            raise ReauthenticationRequired("Sign in again to start a new authenticated session.")
        cookie = self.token_factory()
        digest = session_digest(cookie)
        with self.gateway.transaction(write=True) as store:
            user = store.resolve_identity(identity, now)
            if previous_cookie:
                store.revoke_session(session_digest(previous_cookie))
            store.create_session(digest, user["id"], identity, now, expiry)
            store.audit(now, "oidc", str(user["id"]), "authentication.success", self.token_factory(),
                        {"status": user["status"]})
        return cookie

    def actor(self, cookie: str) -> Actor:
        """Resolve an opaque browser reference, never a user ID supplied by the browser."""
        digest = session_digest(cookie)
        with self.gateway.transaction() as store:
            session = store.session(digest)
            if session is None:
                raise AccessDenied()
            actor = Actor(session["user_id"], digest, self.token_factory())
            self.policy.session(store, actor, active=False)
            return actor

    def account(self, actor: Actor) -> UserRecord:
        """Pending/disabled screens may read only their own profile and status."""
        with self.gateway.transaction() as store:
            self.policy.session(store, actor, active=False)
            user = store.find_user(actor.user_id)
            if user is None:
                raise AccessDenied()
            return user

    def logout(self, actor: Actor) -> None:
        """Revoke one browser's application session, including associated open tabs."""
        with self.gateway.transaction(write=True) as store:
            self.policy.session(store, actor, active=False)
            store.revoke_session(actor.session_hash)
            store.audit(self.policy.clock(), str(actor.user_id), str(actor.user_id), "session.logout", actor.correlation_id, {})

    def activity(self, actor: Actor) -> None:
        """Touch only after an explicit user interaction, never on background polling."""
        with self.gateway.transaction(write=True) as store:
            self.policy.session(store, actor, active=False)
            store.touch_session(actor.session_hash, self.policy.clock())

    def list_users(self, actor: Actor, search: str = "") -> list[UserRecord]:
        """Access administrators can search application accounts independently of employees."""
        with self.gateway.transaction() as store:
            self.policy.require(store, actor, Permission.ACCESS)
            return store.list_users(_safe_text(search, 256))

    def register(self, actor: Actor, issuer: str, subject: str, display_name: str) -> int:
        """Pre-register an exact configured issuer/subject without an email invitation."""
        if issuer != self.issuer:
            raise ValueError("Use the configured OIDC issuer.")
        _safe_text(subject, 512, required=True)
        _safe_text(display_name, 256)
        with self.gateway.transaction(write=True) as store:
            self.policy.require(store, actor, Permission.ACCESS, recent=True)
            user_id = store.register_user(issuer, subject, display_name, self.policy.clock())
            store.audit(self.policy.clock(), str(actor.user_id), str(user_id), "user.register", actor.correlation_id, {"status": "pending"})
            return user_id

    def set_status(self, actor: Actor, user_id: int, status: str) -> None:
        """Change current state atomically without allowing the last administrator to disappear."""
        if status not in USER_STATES:
            raise ValueError("Unknown user status.")
        with self.gateway.transaction(write=True) as store:
            self.policy.require(store, actor, Permission.ACCESS, recent=True)
            user = store.find_user(user_id)
            if user is None:
                raise AccessDenied()
            store.set_status(user_id, status, self.policy.clock())
            if store.active_admin_count() == 0:
                raise ValueError("At least one active access administrator must remain.")
            store.audit(self.policy.clock(), str(actor.user_id), str(user_id), "user.status", actor.correlation_id,
                        {"before": user["status"], "after": status})

    def grant(self, actor: Actor, user_id: int, role: str, scope_data: object) -> int:
        """Grant one fixed role and its own fully resolved scope, with recent authentication."""
        scope = normalize_scope(scope_data)
        validate_assignment(role, scope)
        with self.gateway.transaction(write=True) as store:
            self.policy.require(store, actor, Permission.ACCESS, recent=True)
            if store.find_user(user_id) is None:
                raise AccessDenied()
            store.scope_projects(scope)
            assignment_id = store.grant(user_id, role, scope, self.policy.clock(), str(actor.user_id))
            assignment = store.assignment(assignment_id)
            if assignment is None or assignment["invalid_reason"]:
                raise ValueError("Revoke the invalid assignment before granting its replacement.")
            store.audit(self.policy.clock(), str(actor.user_id), str(user_id), "role.grant", actor.correlation_id,
                        {"assignment_id": assignment_id, "role": role, "scope": scope.to_dict()})
            return assignment_id

    def revoke(self, actor: Actor, assignment_id: int) -> None:
        """Remove a persisted grant and enforce continuity within the writer transaction."""
        with self.gateway.transaction(write=True) as store:
            self.policy.require(store, actor, Permission.ACCESS, recent=True)
            assignment = store.assignment(assignment_id)
            if assignment is None:
                raise AccessDenied()
            store.revoke(assignment_id)
            if store.active_admin_count() == 0:
                raise ValueError("At least one active access administrator must remain.")
            store.audit(self.policy.clock(), str(actor.user_id), str(assignment["user_id"]), "role.revoke",
                        actor.correlation_id, {"assignment_id": assignment_id, "role": assignment["role"]})

    def assignments(self, actor: Actor, user_id: int) -> list[dict[str, object]]:
        """Summarize grants and expose broken references for administrator repair."""
        with self.gateway.transaction() as store:
            self.policy.require(store, actor, Permission.ACCESS)
            result = []
            for row in store.assignments(user_id):
                item: dict[str, object] = dict(row)
                try:
                    if row["invalid_reason"]:
                        raise ValueError(row["invalid_reason"])
                    scope = normalize_scope(json.loads(row["scope_json"]))
                    validate_assignment(row["role"], scope)
                    item["matching_projects"] = len(store.scope_projects(scope))
                    item["problem"] = ""
                except (ValueError, TypeError) as error:
                    item["problem"] = str(error)
                    item["matching_projects"] = 0
                result.append(item)
            return result

    def scope_catalog(self, actor: Actor) -> list[dict[str, object]]:
        """Read only categorical reference labels needed to configure a scope."""
        with self.gateway.transaction() as store:
            self.policy.require(store, actor, Permission.ACCESS)
            return store.scope_catalog()

    def scope_project_choices(self, actor: Actor, search: str = "") -> list[dict[str, object]]:
        """Access administrators may search project labels solely for scope configuration."""
        with self.gateway.transaction() as store:
            self.policy.require(store, actor, Permission.ACCESS)
            return store.scope_project_choices(_safe_text(search, 256))

    def capabilities(self, actor: Actor) -> frozenset[Permission]:
        """Describe currently usable capabilities for UI visibility, never for enforcement."""
        with self.gateway.transaction() as store:
            result = set()
            for permission in Permission:
                for _, scope in self.policy.grants(store, actor, permission):
                    try:
                        usable = scope.kind == "all" or bool(store.scope_projects(scope))
                    except ValueError:
                        usable = False
                    if usable:
                        result.add(permission)
                        break
            return frozenset(result)

    def effective_access(self, actor: Actor, user_id: int, project_id: int) -> list[dict[str, object]]:
        """Explain which current assignments grant access without returning project details."""
        with self.gateway.transaction() as store:
            self.policy.require(store, actor, Permission.ACCESS)
            user = store.find_user(user_id)
            if user is None:
                raise AccessDenied()
            store.scope_projects(ProjectScope("projects", (project_id,)))
            result = []
            for grant in store.assignments(user_id):
                if grant["invalid_reason"] or user["status"] != "active":
                    continue
                try:
                    scope = normalize_scope(json.loads(grant["scope_json"]))
                    validate_assignment(grant["role"], scope)
                    matches = project_id in store.scope_projects(scope)
                except (ValueError, TypeError):
                    continue
                if matches:
                    result.append({"assignment_id": grant["id"], "role": grant["role"],
                                   "permissions": sorted(ROLE_PERMISSIONS[grant["role"]]),
                                   "requires_mfa": self.policy.limits.require_admin_mfa and grant["role"] in APPLICATION_ROLES})
            return result

    def audit(self, actor: Actor) -> list[dict[str, object]]:
        """Read append-only security events with an explicit access-management grant."""
        with self.gateway.transaction() as store:
            self.policy.require(store, actor, Permission.ACCESS)
            return store.list_audit()


class DeploymentAccessService:
    """Deployment-only bootstrap, account inspection, and reasoned recovery."""

    def __init__(self, gateway: AccessGateway, clock: Callable[[], int], operator: str,
                 correlation_factory: Callable[[], str]) -> None:
        self.gateway, self.clock = gateway, clock
        self.operator = _safe_text(operator, 256, required=True)
        self.correlation_factory = correlation_factory

    def pending_accounts(self) -> list[UserRecord]:
        """Inspect bounded pending profiles through trusted deployment access only."""
        with self.gateway.transaction() as store:
            return [user for user in store.list_users("", 200) if user["status"] == "pending"]

    def bootstrap(self, user_id: int) -> None:
        """Grant only access administration exactly once to a verified existing account."""
        with self.gateway.transaction(write=True) as store:
            if store.bootstrap_complete():
                raise ValueError("Initial access setup is already complete. Use explicit recovery if needed.")
            self._appoint(store, user_id, "access.bootstrap", "Initial deployment setup")

    def recover(self, user_id: int, reason: str) -> None:
        """Recover the explicitly verified account and record operator context and reason."""
        reason = _safe_text(reason, 1000, required=True)
        with self.gateway.transaction(write=True) as store:
            self._appoint(store, user_id, "access.recover", reason)

    def _appoint(self, store: AccessStore, user_id: int, action: str, reason: str) -> None:
        if not store.verified_user(user_id):
            raise ValueError("Select an existing account with a verified OIDC login.")
        now = self.clock()
        store.set_status(user_id, "active", now)
        store.grant(user_id, "access_admin", ProjectScope("all"), now, "operator:" + self.operator)
        store.finish_bootstrap()
        store.audit(now, "operator:" + self.operator, str(user_id), action, self.correlation_factory(), {"reason": reason})
