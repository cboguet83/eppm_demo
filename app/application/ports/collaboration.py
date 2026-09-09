"""Typed projections and transaction contracts for project collaboration."""

from contextlib import AbstractContextManager
from typing import Protocol, TypedDict

from app.domain.projects.collaboration import CatalogKind, EventValues


class CatalogEntry(TypedDict):
    """Reference identity with canonical name and localized label."""

    id: int
    name: str
    label: str


class FunctionContact(TypedDict):
    """Function identity and its current occupant display name."""

    function_id: int
    function_name: str
    person: str
    mobile: str
    landline: str


class ProjectContact(FunctionContact):
    """A role assignment resolved against the current organization."""

    id: int
    role_id: int
    role: str


class ProjectEvent(EventValues):
    """One project log entry with translated type and stored timestamps."""

    id: int
    project_id: int
    event_type: str
    created_at: str
    updated_at: str


class CollaborationStore(Protocol):
    """Queries and writes that share one connection and transaction."""

    def list_catalog(self, kind: CatalogKind, locale: str) -> list[CatalogEntry]: ...
    def save_catalog(self, kind: CatalogKind, name: str, item_id: int | None) -> int: ...
    def delete_catalog(self, kind: CatalogKind, item_id: int) -> None: ...
    def list_functions(self) -> list[FunctionContact]: ...
    def list_contacts(self, project_id: int, locale: str) -> list[ProjectContact]: ...
    def save_contact(
        self, project_id: int, role_id: int, function_id: int, contact_id: int | None
    ) -> int: ...
    def delete_contact(self, project_id: int, contact_id: int) -> None: ...
    def reassign_contact(self, project_id: int, contact_id: int, function_id: int) -> None: ...
    def list_events(
        self, project_id: int, locale: str, *, offset: int, limit: int
    ) -> list[ProjectEvent]: ...
    def save_event(self, project_id: int, values: EventValues, event_id: int | None) -> int: ...


class CollaborationGateway(Protocol):
    """Supply a consistent reader or an atomic reserved writer."""

    def transaction(
        self, *, write: bool = False
    ) -> AbstractContextManager[CollaborationStore]: ...
