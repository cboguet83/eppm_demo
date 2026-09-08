"""Presentation assets, locale isolation, and translation cache integrity."""

from contextvars import Context
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.presentation import i18n
from app.presentation.assets import COMPONENT_NAMES, component_path


def test_all_component_resources_are_owned_by_presentation():
    root = Path(i18n.__file__).resolve().parent
    assert len(COMPONENT_NAMES) == 9
    for name in COMPONENT_NAMES:
        path = component_path(name)
        assert path.is_relative_to(root)
        assert (path / "index.html").is_file()
    with pytest.raises(ValueError, match="Unknown presentation component"):
        component_path("../../src")


def test_translation_catalog_copies_cannot_mutate_other_callers():
    original = i18n.load_locale_catalog("en")["nav"]["portfolio"]
    catalog = i18n.load_locale_catalog("en")
    catalog["nav"]["portfolio"] = "Changed outside cache"
    assert i18n.load_locale_catalog("en")["nav"]["portfolio"] == original
    section = i18n.get_section_catalog("gantt", "fr")
    original_label = section["columns"]["name"]
    section["columns"]["name"] = "Changed section"
    assert i18n.get_section_catalog("gantt", "fr")["columns"]["name"] == original_label


def test_non_ui_language_preferences_are_isolated_by_execution_context():
    first, second = Context(), Context()
    first.run(i18n.set_current_locale, "fr")
    second.run(i18n.set_current_locale, "de")
    assert first.run(i18n.get_current_locale) == "fr"
    assert second.run(i18n.get_current_locale) == "de"
    assert Context().run(i18n.get_current_locale) == "en"


def test_language_selectors_remain_independent_between_streamlit_sessions():
    script = """
import streamlit as st
from app.presentation.i18n import SUPPORTED_LOCALES, get_current_locale, set_current_locale, t
def changed():
    set_current_locale(st.session_state['app_language_selector'])
st.selectbox('Language', list(SUPPORTED_LOCALES), key='app_language_selector', on_change=changed)
st.write(get_current_locale())
st.write(t('nav.portfolio'))
"""
    first = AppTest.from_string(script).run()
    second = AppTest.from_string(script).run()
    first.selectbox[0].select("fr").run()
    second.selectbox[0].select("de").run()
    first.run()
    assert not first.exception and not second.exception
    assert first.markdown[0].value == "fr"
    assert second.markdown[0].value == "de"
    assert first.markdown[1].value == "Aperçu du Portefeuille"
    assert second.markdown[1].value == "Portfolio-Übersicht"


def test_locale_lookup_uses_session_fallback_and_ignores_unknown_selector():
    script = """
import streamlit as st
from app.presentation.i18n import get_current_locale
st.write(get_current_locale())
st.session_state['app_language_selector'] = 'unknown'
st.session_state['locale'] = 'pt_br'
st.write(get_current_locale())
"""
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert [item.value for item in app.markdown] == ["en", "pt"]


def test_translation_fallback_aliases_and_interpolation(tmp_path, monkeypatch):
    (tmp_path / "en.json").write_text(
        json.dumps(
            {
                "fallback": "English",
                "count": 3,
                "section": {"default": "Default"},
                "scalar": "not a section",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "fr.json").write_text(
        json.dumps({"section": {"label": "Français"}}), encoding="utf-8"
    )
    monkeypatch.setattr(i18n, "LOCALES_DIR", tmp_path)
    context = Context()
    context.run(i18n.set_current_locale, " FR_fr ")
    assert context.run(i18n.t, "fallback") == "English"
    assert context.run(i18n.t, "count") == "3"
    assert context.run(i18n.t, "section") == "section"
    assert context.run(i18n.t, "missing", default="Hello {name}", name="EPPM") == "Hello EPPM"
    assert (
        context.run(i18n.t, "missing", default="Hello {absent}", name="EPPM") == "Hello {absent}"
    )
    assert context.run(i18n.t, "missing", default="Hello {}", name="EPPM") == "Hello {}"
    assert i18n.get_section_catalog("section", "fr") == {"default": "Default", "label": "Français"}
    assert i18n.get_section_catalog("scalar", "fr") == {}
    assert i18n.normalize_locale(None) == i18n.normalize_locale("not-a-language") == "en"
    assert i18n.load_locale_catalog("de")["fallback"] == "English"


@pytest.mark.parametrize("content", [None, "{invalid", "[]"])
def test_missing_or_malformed_packaged_catalog_is_logged_safely(
    tmp_path, monkeypatch, caplog, content
):
    if content is not None:
        (tmp_path / "en.json").write_text(content, encoding="utf-8")
    monkeypatch.setattr(i18n, "LOCALES_DIR", tmp_path)
    assert i18n.load_locale_catalog("en") == {}
    assert "Translation catalog" in caplog.text
    assert str(tmp_path) not in caplog.text


def test_legacy_i18n_exports_share_the_migrated_owner():
    import src.i18n as legacy
    import src.i18n.translator as translator

    assert legacy.t is translator.t is i18n.t
    assert legacy.set_current_locale is i18n.set_current_locale
