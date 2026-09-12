"""Native hierarchy catalog projections shared by organization and pools."""

from psycopg import Connection

from app.domain.hierarchy import HierarchyType


def hierarchy_types(connection: Connection) -> list[HierarchyType]:
    """Read stable codes and all translations in one authorized query."""
    records: dict[int, HierarchyType] = {}
    for type_id, code, locale, label in connection.execute(
        'SELECT h.id,h.code,t.locale,t.label FROM eppm.hierarchy_type h '
        'LEFT JOIN eppm.hierarchy_type_translation t ON t.hierarchy_type_id=h.id '
        'ORDER BY h.id,t.locale COLLATE "C"'
    ):
        record = records.setdefault(type_id, HierarchyType(code=code, id=type_id))
        if locale is not None:
            record.translations[locale] = label
    return list(records.values())
