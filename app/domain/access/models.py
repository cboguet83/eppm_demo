"""Trusted actors, fixed permission sets, and non-executable project scopes."""

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from collections.abc import Mapping


class Permission(StrEnum):
    """Stable application capabilities, independent of translated role labels."""

    READ = "project.read"
    EDIT = "project.edit"
    APPROVE = "project.approve"
    CREATE = "project.create"
    DELETE = "project.delete"
    PROPERTIES = "project.protected_properties"
    SHARED = "business.manage"
    ACCESS = "access.manage"


ROLE_PERMISSIONS: Mapping[str, frozenset[Permission]] = MappingProxyType({
    "project_viewer": frozenset({Permission.READ}),
    "project_editor": frozenset({Permission.READ, Permission.EDIT}),
    "project_approver": frozenset({Permission.READ, Permission.APPROVE}),
    "access_admin": frozenset({Permission.ACCESS}),
    "business_admin": frozenset({Permission.READ, Permission.EDIT, Permission.CREATE,
                                Permission.DELETE, Permission.PROPERTIES, Permission.SHARED}),
})
APPLICATION_ROLES = frozenset({"access_admin", "business_admin"})
USER_STATES = frozenset({"pending", "active", "disabled"})


class AccessDenied(ValueError):
    """A safe, non-enumerating denial at an application boundary."""

    def __init__(self, message: str = "This operation is unavailable or not permitted.") -> None:
        super().__init__(message)


class ReauthenticationRequired(AccessDenied):
    """The verified provider authentication is too old for this operation."""


@dataclass(frozen=True)
class Actor:
    """Server-resolved session reference; never accept actor fields from components."""

    user_id: int
    session_hash: str = field(repr=False)
    correlation_id: str


@dataclass(frozen=True)
class DeploymentActor:
    """Explicit filesystem-authorized deployment/test caller, never a browser identity."""

    operator: str
    correlation_id: str

    def __post_init__(self) -> None:
        if not self.operator.strip() or not self.correlation_id.strip():
            raise ValueError("Deployment operations require an explicit operator and correlation reference.")


@dataclass(frozen=True)
class VerifiedIdentity:
    """Minimal identity after a maintained OIDC library verifies the ID token."""

    issuer: str
    subject: str
    email: str
    display_name: str
    auth_time: int
    expires_at: int
    mfa: bool


@dataclass(frozen=True)
class PropertyCondition:
    """Stable property and reference IDs with equality or set membership."""

    property_id: str
    operator: str
    value_ids: tuple[int, ...]


@dataclass(frozen=True)
class ProjectScope:
    """One assignment's scope; properties must be resolved against persisted data."""

    kind: str
    project_ids: tuple[int, ...] = ()
    conditions: tuple[PropertyCondition, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return the canonical JSON-safe representation used for persistence."""
        return {"kind": self.kind, "project_ids": list(self.project_ids), "conditions": [
            {"property_id": item.property_id, "operator": item.operator,
             "value_ids": list(item.value_ids)} for item in self.conditions
        ]}


def positive_ids(raw: object) -> tuple[int, ...]:
    """Require a nonempty, bounded list of unique positive reference IDs."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= 10000:
        raise ValueError("Select at least one reference value.")
    if any(type(value) is not int or not 1 <= value <= 9223372036854775807 for value in raw):
        raise ValueError("Reference IDs must be positive integers.")
    return tuple(sorted(set(raw)))


def normalize_scope(raw: object) -> ProjectScope:
    """Reject malformed structures without evaluating any user-supplied expression."""
    if not isinstance(raw, dict) or set(raw) - {"kind", "project_ids", "conditions"}:
        raise ValueError("Invalid scope structure.")
    kind = raw.get("kind")
    projects, conditions = raw.get("project_ids", []), raw.get("conditions", [])
    if kind == "all" and projects == [] and conditions == []:
        return ProjectScope("all")
    if kind == "projects" and conditions == []:
        return ProjectScope("projects", positive_ids(projects))
    if kind != "properties" or projects != [] or not isinstance(conditions, list) or not 1 <= len(conditions) <= 20:
        raise ValueError("Choose all projects, named projects, or nonempty property conditions.")
    normalized = []
    for item in conditions:
        if not isinstance(item, dict) or set(item) != {"property_id", "operator", "value_ids"}:
            raise ValueError("Invalid property condition.")
        property_id, operator = item["property_id"], item["operator"]
        if not isinstance(property_id, str) or not 1 <= len(property_id) <= 128:
            raise ValueError("Invalid property identifier.")
        values = positive_ids(item["value_ids"])
        if not isinstance(operator, str) or operator not in {"eq", "in"} or (operator == "eq" and len(values) != 1):
            raise ValueError("Use equality with one value or membership in a nonempty set.")
        normalized.append(PropertyCondition(property_id, operator, values))
    return ProjectScope("properties", conditions=tuple(normalized))


def validate_assignment(role: str, scope: ProjectScope) -> None:
    """Application-wide roles require explicit all-project scope; roles are fixed."""
    if not isinstance(role, str) or role not in ROLE_PERMISSIONS:
        raise ValueError("Unknown fixed role.")
    if role in APPLICATION_ROLES and scope.kind != "all":
        raise ValueError("Application administrator roles require explicit all-project scope.")
