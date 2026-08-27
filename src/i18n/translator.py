"""Centralized Internationalization (i18n) Service.

Provides in-memory cached JSON translation catalogs, fallback to default locale,
dot-notation key lookup, and parameter interpolation.
"""

import json
from pathlib import Path
from typing import Any, Optional

LOCALES_DIR = Path(__file__).parent / "locales"

SUPPORTED_LOCALES: dict[str, str] = {
    "en": "🇬🇧 English",
    "fr": "🇫🇷 Français",
    "de": "🇩🇪 Deutsch",
    "lb": "🇱🇺 Lëtzebuergesch",
    "pt": "🇵🇹 Português",
}

LOCALE_ALIASES: dict[str, str] = {
    "lu": "lb",
    "lux": "lb",
    "en_us": "en",
    "en_gb": "en",
    "fr_fr": "fr",
    "de_de": "de",
    "pt_pt": "pt",
    "pt_br": "pt",
}

DEFAULT_LOCALE: str = "en"

_CATALOG_CACHE: dict[str, dict[str, Any]] = {}
_ACTIVE_LOCALE_FALLBACK: str = DEFAULT_LOCALE


def load_locale_catalog(locale: str) -> dict[str, Any]:
    """Loads and caches JSON translation dictionary for a given locale.

    Args:
        locale: Two-letter locale code (e.g. 'en', 'fr', 'de', 'lb', 'pt', 'lu').

    Returns:
        dict[str, Any]: Translation key-value catalog.
    """
    clean_locale = locale.lower().strip() if locale else DEFAULT_LOCALE
    clean_locale = LOCALE_ALIASES.get(clean_locale, clean_locale)
    if clean_locale not in SUPPORTED_LOCALES:
        clean_locale = DEFAULT_LOCALE

    if clean_locale not in _CATALOG_CACHE:
        file_path = LOCALES_DIR / f"{clean_locale}.json"
        if not file_path.exists():
            file_path = LOCALES_DIR / f"{DEFAULT_LOCALE}.json"

        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                _CATALOG_CACHE[clean_locale] = json.load(f)
        else:
            _CATALOG_CACHE[clean_locale] = {}

    return _CATALOG_CACHE[clean_locale]


def get_current_locale() -> str:
    """Returns current active locale code from Streamlit session state or fallback.

    Returns:
        str: Active locale code (e.g. 'en', 'fr', 'de', 'lb', 'pt').
    """
    try:
        import streamlit as st

        if hasattr(st, "session_state"):
            for key in ("app_language_selector", "locale"):
                if key in st.session_state and st.session_state[key]:
                    raw_val = str(st.session_state[key]).lower().strip()
                    val = LOCALE_ALIASES.get(raw_val, raw_val)
                    if val in SUPPORTED_LOCALES:
                        return val
    except Exception:
        pass

    return _ACTIVE_LOCALE_FALLBACK


def set_current_locale(locale: str) -> None:
    """Sets active locale in Streamlit session state and fallback tracker.

    Args:
        locale: Target locale code.
    """
    clean_locale = locale.lower().strip() if locale else DEFAULT_LOCALE
    clean_locale = LOCALE_ALIASES.get(clean_locale, clean_locale)
    if clean_locale not in SUPPORTED_LOCALES:
        clean_locale = DEFAULT_LOCALE

    global _ACTIVE_LOCALE_FALLBACK
    _ACTIVE_LOCALE_FALLBACK = clean_locale

    try:
        import streamlit as st

        if hasattr(st, "session_state"):
            st.session_state["locale"] = clean_locale
            st.session_state["app_language_selector"] = clean_locale
    except Exception:
        pass


def _resolve_nested_key(dict_obj: dict[str, Any], path: str) -> Optional[str]:
    """Resolves a dot-notation key (e.g. 'nav.portfolio') from a nested dictionary.

    Args:
        dict_obj: Translation catalog.
        path: Dot-separated key path.

    Returns:
        Optional[str]: Found string value or None.
    """
    keys = path.split(".")
    curr = dict_obj
    for k in keys:
        if isinstance(curr, dict) and k in curr:
            curr = curr[k]
        else:
            return None
    return str(curr) if isinstance(curr, (str, int, float)) else None


def t(key: str, default: Optional[str] = None, **kwargs: Any) -> str:
    """Translates a dot-notation key for the currently active locale.

    Falls back to English if the key is missing in the target language.

    Args:
        key: Dot-separated string key (e.g. 'portfolio.planned_budget').
        default: Optional fallback string if key is not found in any catalog.
        **kwargs: Named parameters for string interpolation (e.g. project_id="PRJ-001").

    Returns:
        str: Translated and formatted text string.
    """
    locale = get_current_locale()
    catalog = load_locale_catalog(locale)
    fallback_catalog = load_locale_catalog(DEFAULT_LOCALE)

    val = _resolve_nested_key(catalog, key)
    if val is None and locale != DEFAULT_LOCALE:
        val = _resolve_nested_key(fallback_catalog, key)

    if val is None:
        val = default if default is not None else key

    if kwargs:
        try:
            return val.format(**kwargs)
        except (KeyError, ValueError):
            return val

    return val


def get_section_catalog(section: str, locale: Optional[str] = None) -> dict[str, Any]:
    """Retrieves an entire dictionary subsection merged with fallback for frontend passing.

    Args:
        section: Root section key (e.g. 'gantt').
        locale: Optional locale code; defaults to active locale.

    Returns:
        dict[str, Any]: Merged section dictionary.
    """
    target_locale = locale or get_current_locale()
    catalog = load_locale_catalog(target_locale)
    fallback = load_locale_catalog(DEFAULT_LOCALE)

    fb_sec = fallback.get(section, {})
    target_sec = catalog.get(section, {})

    if not isinstance(fb_sec, dict):
        fb_sec = {}
    if not isinstance(target_sec, dict):
        target_sec = {}

    merged = dict(fb_sec)
    merged.update(target_sec)
    return merged
