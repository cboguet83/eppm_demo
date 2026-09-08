"""Presentation-owned translations and locale state isolated between sessions."""

from contextvars import ContextVar
from copy import deepcopy
from functools import lru_cache
import json
import logging
from pathlib import Path

LOCALES_DIR = Path(__file__).parent / "assets" / "locales"
DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = {
    "en": "🇬🇧 English",
    "fr": "🇫🇷 Français",
    "de": "🇩🇪 Deutsch",
    "lb": "🇱🇺 Lëtzebuergesch",
    "pt": "🇵🇹 Português",
}
LOCALE_ALIASES = {
    "lu": "lb",
    "lux": "lb",
    "en_us": "en",
    "en_gb": "en",
    "fr_fr": "fr",
    "de_de": "de",
    "pt_pt": "pt",
    "pt_br": "pt",
}
_fallback_locale: ContextVar[str] = ContextVar("eppm_locale", default=DEFAULT_LOCALE)
logger = logging.getLogger(__name__)


def normalize_locale(locale: str | None) -> str:
    """Resolve supported aliases and fall back to English for unknown locales."""
    code = locale.lower().strip() if locale else DEFAULT_LOCALE
    code = LOCALE_ALIASES.get(code, code)
    return code if code in SUPPORTED_LOCALES else DEFAULT_LOCALE


@lru_cache(maxsize=5)
def _read_catalog(locale: str, directory: Path) -> dict[str, object]:
    """Cache packaged JSON dictionaries privately; callers receive copies."""
    path = directory / f"{locale}.json"
    if not path.exists():
        path = directory / f"{DEFAULT_LOCALE}.json"
    try:
        with path.open(encoding="utf-8") as source:
            catalog = json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Translation catalog could not be loaded (%s)", type(error).__name__)
        return {}
    if not isinstance(catalog, dict):
        logger.warning("Translation catalog must contain a JSON object")
        return {}
    return catalog


def load_locale_catalog(locale: str) -> dict[str, object]:
    """Return a copy of a locale's catalog without exposing shared cached data.

    Catalog values are nested JSON objects at the packaged-resource boundary.
    """
    return deepcopy(_read_catalog(normalize_locale(locale), LOCALES_DIR))


def get_current_locale() -> str:
    """Read the current Streamlit session, or the caller's non-UI context."""
    import streamlit as st
    from streamlit.runtime.scriptrunner import get_script_run_ctx

    if get_script_run_ctx(suppress_warning=True) is not None:
        for key in ("app_language_selector", "locale"):
            value = st.session_state.get(key)
            if value:
                code = str(value).lower().strip()
                code = LOCALE_ALIASES.get(code, code)
                if code in SUPPORTED_LOCALES:
                    return code
        return DEFAULT_LOCALE
    return _fallback_locale.get()


def set_current_locale(locale: str) -> None:
    """Set only the active session or execution context's language preference."""
    import streamlit as st
    from streamlit.runtime.scriptrunner import get_script_run_ctx

    code = normalize_locale(locale)
    if get_script_run_ctx(suppress_warning=True) is None:
        _fallback_locale.set(code)
        return
    st.session_state["locale"] = code
    if st.session_state.get("app_language_selector") != code:
        st.session_state["app_language_selector"] = code


def _resolve_nested_key(catalog: dict[str, object], path: str) -> str | None:
    """Resolve dotted translation keys without returning nested dictionaries."""
    current: object = catalog
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return str(current) if isinstance(current, (str, int, float)) else None


def t(key: str, default: str | None = None, **kwargs: object) -> str:
    """Translate a dotted key, with English fallback and named interpolation."""
    locale = get_current_locale()
    value = _resolve_nested_key(_read_catalog(locale, LOCALES_DIR), key)
    if value is None and locale != DEFAULT_LOCALE:
        value = _resolve_nested_key(_read_catalog(DEFAULT_LOCALE, LOCALES_DIR), key)
    if value is None:
        value = default if default is not None else key
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, ValueError, IndexError):
            return value
    return value


def get_section_catalog(section: str, locale: str | None = None) -> dict[str, object]:
    """Copy a component's catalog section with the existing shallow fallback merge."""
    target = _read_catalog(normalize_locale(locale or get_current_locale()), LOCALES_DIR)
    fallback = _read_catalog(DEFAULT_LOCALE, LOCALES_DIR)
    fallback_section = fallback.get(section, {})
    target_section = target.get(section, {})
    merged = dict(fallback_section) if isinstance(fallback_section, dict) else {}
    if isinstance(target_section, dict):
        merged.update(target_section)
    return deepcopy(merged)
