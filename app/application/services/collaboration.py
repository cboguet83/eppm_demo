"""Project contacts, reference catalogs, and log use cases."""

from app.application.ports.collaboration import (
    CatalogEntry,
    CollaborationGateway,
    FunctionContact,
    ProjectContact,
    ProjectEvent,
)
from app.domain.projects.collaboration import (
    CatalogKind,
    EventValues,
    normalize_event,
    required_text,
    validate_catalog,
)


class CollaborationService:
    """Validate requests and coordinate injected collaboration transactions."""

    def __init__(self, gateway: CollaborationGateway) -> None:
        """Inject persistence without opening a database connection."""
        self._gateway = gateway

    def list_catalog(self, kind: CatalogKind, locale: str = "en") -> list[CatalogEntry]:
        """Read localized reference labels with canonical-name fallback."""
        validate_catalog(kind)
        with self._gateway.transaction() as store:
            return store.list_catalog(kind, locale)

    def save_catalog(self, kind: CatalogKind, name: str, item_id: int | None = None) -> int:
        """Create or rename a reference and its English translation atomically."""
        validate_catalog(kind)
        name = required_text(name, "Name")
        with self._gateway.transaction(write=True) as store:
            return store.save_catalog(kind, name, item_id)

    def delete_catalog(self, kind: CatalogKind, item_id: int) -> None:
        """Delete an unused reference, retaining protection for existing usage."""
        validate_catalog(kind)
        with self._gateway.transaction(write=True) as store:
            store.delete_catalog(kind, item_id)

    def list_functions(self) -> list[FunctionContact]:
        """Read current occupants, using the function name when vacant."""
        with self._gateway.transaction() as store:
            return store.list_functions()

    def list_contacts(self, project_id: int, locale: str = "en") -> list[ProjectContact]:
        """Resolve one project's assignments and occupants in one snapshot."""
        with self._gateway.transaction() as store:
            return store.list_contacts(project_id, locale)

    def save_contact(
        self, project_id: int, role_id: int, function_id: int, contact_id: int | None = None
    ) -> int:
        """Create or edit an assignment within the specified project."""
        with self._gateway.transaction(write=True) as store:
            return store.save_contact(project_id, role_id, function_id, contact_id)

    def delete_contact(self, project_id: int, contact_id: int) -> None:
        """Remove only the specified project's assignment."""
        with self._gateway.transaction(write=True) as store:
            store.delete_contact(project_id, contact_id)

    def list_events(
        self, project_id: int, locale: str = "en", *, offset: int = 0, limit: int = 50
    ) -> list[ProjectEvent]:
        """Read a bounded newest-first log page with translated event types."""
        if type(limit) is not int or type(offset) is not int:
            raise ValueError("Invalid event page request.")
        with self._gateway.transaction() as store:
            return store.list_events(
                project_id, locale, offset=max(0, offset), limit=min(100, max(1, limit))
            )

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
        """Validate and save an event without allowing cross-project updates."""
        values = normalize_event(
            EventValues(
                title=title,
                description=description,
                deadline=deadline,
                scope=scope,
                comment=comment,
                event_type_id=event_type_id,
                status=status,
            )
        )
        with self._gateway.transaction(write=True) as store:
            return store.save_event(project_id, values, event_id)
