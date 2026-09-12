"""Shared optional hierarchy classifications and localized catalog labels."""

from dataclasses import dataclass, field, replace
import re


@dataclass(frozen=True)
class HierarchyType:
    """A stable code with editable labels shared by teams, pools, and groups."""

    code: str
    translations: dict[str, str] = field(default_factory=dict)
    id: int | None = None

    def label(self, locale: str) -> str:
        """Return the requested label, falling back to English and the code."""
        return self.translations.get(locale) or self.translations.get("en") or self.code


def normalize_hierarchy_type(value: HierarchyType) -> HierarchyType:
    """Validate a stable code and nonblank labels for supported languages."""
    if not isinstance(value.code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value.code.strip()):
        raise ValueError("Hierarchy type code must use lowercase letters, digits, or underscores.")
    if not isinstance(value.translations, dict) or not value.translations:
        raise ValueError("Provide at least one hierarchy type label.")
    labels = {}
    for locale, label in value.translations.items():
        if locale not in {"en", "fr", "de", "lb", "pt"}:
            raise ValueError("Unsupported hierarchy type language.")
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 120:
            raise ValueError("Hierarchy type labels must contain 1 to 120 characters.")
        labels[locale] = label.strip()
    return replace(value, code=value.code.strip(), translations=labels)


def validate_hierarchy_type_id(value: int | None) -> None:
    """Accept an unassigned classification or a positive catalog identity."""
    if value is not None and (type(value) is not int or value <= 0):
        raise ValueError("Hierarchy type must be a valid catalog selection or empty.")
