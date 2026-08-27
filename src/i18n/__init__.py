"""Internationalization (i18n) package for EPPM."""

from src.i18n.translator import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    get_current_locale,
    get_section_catalog,
    load_locale_catalog,
    set_current_locale,
    t,
)

__all__ = [
    "DEFAULT_LOCALE",
    "SUPPORTED_LOCALES",
    "get_current_locale",
    "get_section_catalog",
    "load_locale_catalog",
    "set_current_locale",
    "t",
]
