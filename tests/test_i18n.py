"""Unit Tests for Internationalization (i18n) Module."""

import unittest
from app.presentation.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    get_current_locale,
    get_section_catalog,
    load_locale_catalog,
    set_current_locale,
    t,
)


class TestI18n(unittest.TestCase):
    """Test suite covering i18n catalogs, key integrity, fallback mechanisms, and interpolation."""

    def setUp(self) -> None:
        """Reset locale to default English before each test."""
        set_current_locale(DEFAULT_LOCALE)

    def test_supported_locales_presence(self) -> None:
        """Verify all 5 target languages are declared."""
        self.assertIn("en", SUPPORTED_LOCALES)
        self.assertIn("fr", SUPPORTED_LOCALES)
        self.assertIn("de", SUPPORTED_LOCALES)
        self.assertIn("lb", SUPPORTED_LOCALES)
        self.assertIn("pt", SUPPORTED_LOCALES)

    def test_catalogs_load_valid_json(self) -> None:
        """Verify each locale JSON file loads valid dictionary data."""
        for code in SUPPORTED_LOCALES:
            catalog = load_locale_catalog(code)
            self.assertIsInstance(catalog, dict, f"Catalog for {code} is not a dictionary")
            self.assertIn("app", catalog, f"Missing 'app' root namespace in {code}.json")
            self.assertIn("nav", catalog, f"Missing 'nav' root namespace in {code}.json")
            self.assertIn("portfolio", catalog, f"Missing 'portfolio' root namespace in {code}.json")
            self.assertIn("master_data", catalog, f"Missing 'master_data' root namespace in {code}.json")
            self.assertIn("schema", catalog, f"Missing 'schema' root namespace in {code}.json")
            self.assertIn("planning", catalog, f"Missing 'planning' root namespace in {code}.json")
            self.assertIn("gantt", catalog, f"Missing 'gantt' root namespace in {code}.json")

    def test_key_parity_across_languages(self) -> None:
        """Verify all keys present in English exist across all target languages."""
        en_catalog = load_locale_catalog("en")

        def _get_all_leaf_keys(d: dict, prefix: str = "") -> set[str]:
            keys = set()
            for k, v in d.items():
                full_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    keys.update(_get_all_leaf_keys(v, full_key))
                else:
                    keys.add(full_key)
            return keys

        en_keys = _get_all_leaf_keys(en_catalog)

        for lang in ("fr", "de", "lb", "pt"):
            target_catalog = load_locale_catalog(lang)
            target_keys = _get_all_leaf_keys(target_catalog)
            missing = en_keys - target_keys
            self.assertEqual(
                len(missing),
                0,
                f"Locale '{lang}' is missing keys present in English: {missing}",
            )

    def test_translation_helper_and_interpolation(self) -> None:
        """Verify t() resolves dot notation and interpolates parameters."""
        set_current_locale("en")
        self.assertEqual(t("nav.portfolio"), "Portfolio Overview")
        self.assertEqual(t("planning.schedule_title", project_id=1), "Timeline Schedule: 1")

        set_current_locale("fr")
        self.assertEqual(t("nav.portfolio"), "Aperçu du Portefeuille")
        self.assertEqual(t("planning.schedule_title", project_id=1), "Calendrier du Projet : 1")

        set_current_locale("de")
        self.assertEqual(t("nav.portfolio"), "Portfolio-Übersicht")

        set_current_locale("lb")
        self.assertEqual(t("nav.portfolio"), "Portefeuille Iwwersiicht")

        set_current_locale("pt")
        self.assertEqual(t("nav.portfolio"), "Visão Geral do Portfólio")

    def test_fallback_to_english(self) -> None:
        """Verify nonexistent key in target language falls back to English catalog."""
        set_current_locale("fr")
        # Existing key
        self.assertEqual(t("app.badge_sqlite"), "Base SQLite")

        # Non-existent key everywhere returns the key itself or explicit default
        self.assertEqual(t("non.existent.key"), "non.existent.key")
        self.assertEqual(t("non.existent.key", default="Custom Fallback"), "Custom Fallback")

    def test_get_section_catalog(self) -> None:
        """Verify section catalogs for Gantt JavaScript frontend are properly extracted."""
        gantt_fr = get_section_catalog("gantt", "fr")
        self.assertIn("columns", gantt_fr)
        self.assertEqual(gantt_fr["columns"]["name"], "Nom de la Tâche / Étape")
        self.assertEqual(gantt_fr["columns"]["desc"], "Description")

    def test_lu_alias_resolution(self) -> None:
        """Verify 'lu' alias correctly maps to Luxembourgish 'lb' catalog."""
        set_current_locale("lu")
        self.assertEqual(get_current_locale(), "lb")
        self.assertEqual(t("nav.portfolio"), "Portefeuille Iwwersiicht")
        self.assertEqual(t("portfolio.title"), "Portefeuille Analytik & Dynamesch Iwwersiicht")
        self.assertEqual(t("portfolio.kpi_total_projects"), "Total Projeten")


if __name__ == "__main__":
    unittest.main()
