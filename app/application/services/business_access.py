"""Explicit business-operation actor context and transaction-bound authorization."""

from collections.abc import Collection
from dataclasses import dataclass
from types import MappingProxyType

from app.application.ports.access import AccessStore
from app.application.ports.business_permissions import PermissionSnapshot
from app.application.services.access import AuthorizationPolicy
from app.domain.access.models import AccessDenied, Actor, DeploymentActor, Permission, ProjectScope


@dataclass(frozen=True)
class BusinessAccess:
    """Bind an actor and policy explicitly; permission decisions use the supplied transaction."""

    actor: Actor | DeploymentActor
    policy: AuthorizationPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.actor, (Actor, DeploymentActor)):
            raise AccessDenied()

    def require(self, store: AccessStore, permission: Permission,
                project_ids: Collection[int] | None = None) -> None:
        """Check the current application actor or the explicit trusted deployment context."""
        if isinstance(self.actor, Actor):
            self.policy.require(store, self.actor, permission, project_ids)

    def projects(self, store: AccessStore) -> set[int]:
        """Return the actor's current read scope before business query pagination/aggregation."""
        if isinstance(self.actor, DeploymentActor):
            return store.scope_projects(ProjectScope("all"))
        allowed = self.policy.projects(store, self.actor)
        if not allowed:
            # An explicit global reader can browse an empty portfolio. Invalid scopes
            # and active accounts without business grants cannot browse reference data.
            self.policy.require(store, self.actor, Permission.READ)
        return allowed

    def global_permission(self, store: AccessStore, permission: Permission) -> bool:
        """Test UI/reference visibility without supplying an implicit permission fallback."""
        try:
            self.require(store, permission)
        except AccessDenied:
            return False
        return True

    def describe(self, store: AccessStore) -> PermissionSnapshot:
        """Read one current UI projection without mixing permission scopes or trusting components."""
        self.projects(store)
        global_permissions = frozenset(permission for permission in Permission
                                       if self.global_permission(store, permission))
        scoped = {}
        if isinstance(self.actor, Actor):
            scoped = {permission: frozenset(self.policy.projects(store, self.actor, permission))
                      for permission in Permission if permission not in global_permissions}
        return PermissionSnapshot(global_permissions, MappingProxyType(scoped))

    @property
    def audit_actor(self) -> str:
        """Return only the trusted internal user or operator reference for audit."""
        if isinstance(self.actor, Actor):
            return str(self.actor.user_id)
        return "operator:" + self.actor.operator
