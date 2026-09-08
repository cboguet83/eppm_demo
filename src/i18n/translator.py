"""Compatibility exports for presentation-owned translations and locale state."""

from app.presentation.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    LOCALE_ALIASES,
    LOCALES_DIR,
    get_current_locale,
    get_section_catalog,
    load_locale_catalog,
    set_current_locale,
    t,
)

__all__ = [
    "DEFAULT_LOCALE",
    "SUPPORTED_LOCALES",
    "LOCALE_ALIASES",
    "LOCALES_DIR",
    "get_current_locale",
    "get_section_catalog",
    "load_locale_catalog",
    "set_current_locale",
    "t",
]
