"""Current permission projections for UI visibility, never mutation authorization."""

from collections.abc import Mapping
from dataclasses import dataclass

from app.domain.access.models import Permission


@dataclass(frozen=True)
class PermissionSnapshot:
    """Describe global capabilities and their independently scoped project sets."""

    global_permissions: frozenset[Permission]
    project_permissions: Mapping[Permission, frozenset[int]]

    def allows(self, permission: Permission, project_id: int | None = None) -> bool:
        """Choose UI controls; the service must still authorize every actual operation."""
        return permission in self.global_permissions or (
            project_id is not None and project_id in self.project_permissions.get(permission, frozenset())
        )
