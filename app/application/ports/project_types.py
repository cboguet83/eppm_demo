"""Transactional persistence contracts for project-type use cases."""

from contextlib import AbstractContextManager
from typing import Protocol

from app.domain.projects.project_types import (
    ProjectType, PropertyApplicability, PropertyDefinition, PropertyValue,
)


class ProjectTypeStore(Protocol):
    """Operations sharing a single application-owned transaction."""

    def list_types(self) -> list[ProjectType]:
        """Return types ordered with General first, then by name."""
        ...

    def find_type(self, type_id: int) -> ProjectType | None:
        """Return the type if it exists."""
        ...

    def insert_type(self, name: str, description: str) -> int:
        """Persist validated details and return the new identifier."""
        ...

    def update_type(self, type_id: int, name: str, description: str) -> None:
        """Persist validated changes to an existing type."""
        ...

    def delete_type(self, type_id: int) -> None:
        """Delete a type after its deletion guards have passed."""
        ...

    def has_projects(self, type_id: int) -> bool:
        """Report whether projects still reference the type."""
        ...

    def has_exclusive_properties(self, type_id: int) -> bool:
        """Report selected-only properties assigned solely to this type."""
        ...

    def property_definitions(self) -> list[PropertyDefinition]:
        """Return ordered business definitions for all properties."""
        ...

    def selected_properties(self, type_id: int) -> set[str]:
        """Return property IDs explicitly assigned to this type."""
        ...

    def required_overrides(self, type_id: int) -> dict[str, bool | int | None]:
        """Return nullable required overrides for this type."""
        ...

    def defaults(self, type_id: int) -> dict[str, PropertyValue]:
        """Return stored defaults, preserving absent and cleared values."""
        ...

    def get_applicability(self, param_id: str) -> PropertyApplicability | None:
        """Return scope, or None when the property does not exist."""
        ...

    def set_applicability(self, param_id: str, scope: PropertyApplicability) -> None:
        """Replace the property's scope within the current transaction."""
        ...

    def save_rule(
        self, type_id: int, param_id: str, mandatory_override: bool | None,
        *, has_default: bool, default_value: PropertyValue,
    ) -> None:
        """Save the required override and validated typed default atomically."""
        ...


class ProjectTypeGateway(Protocol):
    """Provide committed-or-rolled-back sessions without exposing DB objects."""

    def transaction(self, *, write: bool = False) -> AbstractContextManager[ProjectTypeStore]:
        """Open a consistent read or an atomic guarded write operation."""
        ...
