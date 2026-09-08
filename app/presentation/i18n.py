"""Bridge to the existing shared locale state during the staged migration."""

from src.i18n import get_current_locale, get_section_catalog, t

__all__ = ["t", "get_current_locale", "get_section_catalog"]
