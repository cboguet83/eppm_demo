"""Stable collaboration codes and validation independent of storage and UI."""

from datetime import date
from typing import Literal, TypedDict

type CatalogKind = Literal["role", "event_type"]
EVENT_STATUSES = ("new", "active", "completed", "cancelled", "rejected", "closed")
EVENT_SCOPES = ("internal", "global")


class EventValues(TypedDict):
    """Validated fields accepted by a project event write."""

    title: str
    description: str
    deadline: str | None
    scope: str
    comment: str
    event_type_id: int
    status: str


def validate_catalog(kind: CatalogKind) -> CatalogKind:
    """Allow only the two existing reference catalogs."""
    if kind not in ("role", "event_type"):
        raise ValueError("Unknown project catalog.")
    return kind


def required_text(value: str, label: str) -> str:
    """Trim a required label and reject empty or non-text input."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required.")
    return value.strip()


def normalize_event(values: EventValues) -> EventValues:
    """Validate event fields without changing stable scope or state codes."""
    title = required_text(values["title"], "Title")
    if values["scope"] not in EVENT_SCOPES or values["status"] not in EVENT_STATUSES:
        raise ValueError("Invalid event scope or state.")
    if not isinstance(values["description"], str) or not isinstance(values["comment"], str):
        raise ValueError("Event description and comment must be text.")
    deadline = values["deadline"]
    if deadline is not None:
        if not isinstance(deadline, str):
            raise ValueError("Invalid event deadline.")
        try:
            deadline = date.fromisoformat(deadline).isoformat()
        except ValueError as exc:
            raise ValueError("Invalid event deadline.") from exc
    return {**values, "title": title, "deadline": deadline}
