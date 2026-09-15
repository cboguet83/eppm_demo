"""Pool type identities, localized names, and cycle-safe parent validation."""

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class PoolType:
    """A named pool classification with an optional parent classification."""

    name: str
    id: int | None = None
    parent_pool_type_id: int | None = None
    translations: dict[str, str] = field(default_factory=dict)

    def label(self, locale: str) -> str:
        """Use a translated display name, falling back to the canonical name."""
        return self.translations.get(locale) or self.name


def normalize_pool_type(item: PoolType, existing: list[PoolType]) -> PoolType:
    """Validate names, identities, and ancestry before a catalog transaction writes."""
    if not isinstance(item.name, str) or not 1 <= len(item.name.strip()) <= 120:
        raise ValueError("Pool type name must contain 1 to 120 characters.")
    for identity in (item.id, item.parent_pool_type_id):
        if identity is not None and (type(identity) is not int or identity <= 0):
            raise ValueError("Pool type identities must be positive integers.")
    by_id = {record.id: record for record in existing}
    if item.id is not None and item.id not in by_id:
        raise ValueError("This pool type no longer exists.")
    visited = {item.id} if item.id is not None else set()
    parent = item.parent_pool_type_id
    while parent is not None:
        if parent in visited:
            raise ValueError("Pool type parent links cannot be circular.")
        if parent not in by_id:
            raise ValueError("The parent pool type no longer exists.")
        visited.add(parent)
        parent = by_id[parent].parent_pool_type_id
    if not isinstance(item.translations, dict):
        raise ValueError("Pool type translations must map languages to names.")
    labels = {}
    for locale, label in item.translations.items():
        if locale not in {"en", "fr", "de", "lb", "pt"}:
            raise ValueError("Unsupported pool type translation language.")
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 120:
            raise ValueError("Pool type translations must contain 1 to 120 characters.")
        labels[locale] = label.strip()
    labels["en"] = item.name.strip()
    return replace(item, name=item.name.strip(), translations=labels)
