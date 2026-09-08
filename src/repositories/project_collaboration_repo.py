"""Compatibility facade retaining the old collaboration path and error contracts."""

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
from app.application.exceptions import CollaborationConflictError, CollaborationStorageError
from app.application.ports.collaboration import (
    CatalogEntry,
    FunctionContact,
    ProjectContact,
    ProjectEvent,
)
from app.domain.projects.collaboration import CatalogKind, EVENT_SCOPES, EVENT_STATUSES
from app.main import create_collaboration_service


@contextmanager
def legacy_collaboration_errors() -> Iterator[None]:
    """Keep historical SQLite error types at the legacy adapter boundary."""
    try:
        yield
    except (CollaborationConflictError, CollaborationStorageError) as error:
        if isinstance(error.__cause__, sqlite3.DatabaseError):
            raise error.__cause__ from error
        raise


class ProjectCollaborationRepository:
    """Delegate historical repository methods to the collaboration service."""

    def __init__(self, db_path: str | None = None) -> None:
        """Retain the legacy database path for existing callers."""
        self.db_path = db_path
        self.service = create_collaboration_service(db_path)

    def list_catalog(self, kind: CatalogKind, locale: str = "en") -> list[CatalogEntry]:
        """Delegate list catalog with historical error types."""
        with legacy_collaboration_errors():
            return self.service.list_catalog(kind, locale)

    def save_catalog(self, kind: CatalogKind, name: str, item_id: int | None = None) -> int:
        """Delegate save catalog with historical error types."""
        with legacy_collaboration_errors():
            return self.service.save_catalog(kind, name, item_id)

    def delete_catalog(self, kind: CatalogKind, item_id: int) -> None:
        """Delegate delete catalog with historical error types."""
        with legacy_collaboration_errors():
            return self.service.delete_catalog(kind, item_id)

    def list_functions(self) -> list[FunctionContact]:
        """Delegate list functions with historical error types."""
        with legacy_collaboration_errors():
            return self.service.list_functions()

    def list_contacts(self, project_id: int, locale: str = "en") -> list[ProjectContact]:
        """Delegate list contacts with historical error types."""
        with legacy_collaboration_errors():
            return self.service.list_contacts(project_id, locale)

    def save_contact(
        self, project_id: int, role_id: int, function_id: int, contact_id: int | None = None
    ) -> int:
        """Delegate save contact with historical error types."""
        with legacy_collaboration_errors():
            return self.service.save_contact(project_id, role_id, function_id, contact_id)

    def delete_contact(self, project_id: int, contact_id: int) -> None:
        """Delegate delete contact with historical error types."""
        with legacy_collaboration_errors():
            return self.service.delete_contact(project_id, contact_id)

    def list_events(
        self, project_id: int, locale: str = "en", *, offset: int = 0, limit: int = 50
    ) -> list[ProjectEvent]:
        """Delegate list events with historical error types."""
        with legacy_collaboration_errors():
            return self.service.list_events(project_id, locale, offset=offset, limit=limit)

    def save_event(
        self,
        project_id: int,
        *,
        title: str,
        description: str,
        deadline: str | None,
        scope: str,
        comment: str,
        event_type_id: int,
        status: str = "new",
        event_id: int | None = None
    ) -> int:
        """Delegate save event with historical error types."""
        with legacy_collaboration_errors():
            return self.service.save_event(
                project_id,
                title=title,
                description=description,
                deadline=deadline,
                scope=scope,
                comment=comment,
                event_type_id=event_type_id,
                status=status,
                event_id=event_id,
            )
