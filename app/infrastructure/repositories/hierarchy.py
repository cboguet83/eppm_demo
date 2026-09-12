"""Shared hierarchy catalog reads inside existing authorized transactions."""

import sqlite3

from app.domain.hierarchy import HierarchyType


def hierarchy_types(connection: sqlite3.Connection) -> list[HierarchyType]:
    """Load all labels in one query for organization and resource-pool selectors."""
    records: dict[int, HierarchyType] = {}
    for type_id, code, locale, label in connection.execute(
        "SELECT h.id,h.code,t.locale,t.label FROM hierarchy_type h "
        "LEFT JOIN hierarchy_type_translation t ON t.hierarchy_type_id=h.id ORDER BY h.id,t.locale"
    ):
        record = records.setdefault(type_id, HierarchyType(code=code, id=type_id))
        if locale is not None:
            record.translations[locale] = label
    return list(records.values())
