"""Application import, navigation, CLI and projection integration checks."""

import unittest

from app.presentation.components.planning_catalog import flatten_dynamic_attributes


class TestIntegration(unittest.TestCase):
    """Keep import and presentation contracts independent of database setup."""

    def test_all_application_modules_import_cleanly(self) -> None:
        """Verify application modules import without unresolved dependencies."""
        import importlib
        import pkgutil
        import app

        for module_info in pkgutil.walk_packages(app.__path__, prefix="app."):
            mod = importlib.import_module(module_info.name)
            self.assertIsNotNone(mod)


    def test_no_direct_app_sidebar_nav_assignment_in_views(self) -> None:
        """Verify that presentation views do not write directly to st.session_state['app_sidebar_nav'].

        Direct writes to a rendered widget key trigger StreamlitWidgetAlreadyInstantiatedError.
        All programmatic transitions must use st.session_state['nav_redirect'].
        """
        import re
        from pathlib import Path

        views_dir = Path("app/presentation/pages")
        pattern = re.compile(r'st\.session_state\[(["\'])app_sidebar_nav\1\]\s*=')

        violations = []
        for py_file in views_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            for line_num, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    violations.append(f"{py_file.name}:{line_num}: {line.strip()}")

        self.assertEqual(
            violations,
            [],
            f"Views must use 'nav_redirect' instead of modifying 'app_sidebar_nav' directly: {violations}",
        )


    def test_allowed_dynamic_params_excludes_code_station(self) -> None:
        """Verify code_station is excluded from project master list grid but allowed params remain."""
        from app.presentation.pages.portfolio import ALLOWED_DYNAMIC_PARAMS

        self.assertNotIn("code_station", ALLOWED_DYNAMIC_PARAMS)
        expected_allowed = {
            "phase",
            "code_line",
            "strategic_priority",
            "category",
            "category_tags",
            "complexity",
        }
        self.assertEqual(ALLOWED_DYNAMIC_PARAMS, expected_allowed)


    def test_portfolio_row_click_is_applied_before_table_render(self) -> None:
        """The component event must synchronize the stable project ID before mounting."""
        import streamlit as st

        from app.presentation.pages.portfolio import _sync_portfolio_project_selection

        component_key = "test_portfolio_master_table"
        selection_key = "test_selected_portfolio_project_id"
        try:
            st.session_state[component_key] = {"row_click": 42}
            st.session_state[selection_key] = 7

            _sync_portfolio_project_selection(component_key, selection_key)

            self.assertEqual(st.session_state[selection_key], 42)
        finally:
            st.session_state.pop(component_key, None)
            st.session_state.pop(selection_key, None)


    def test_parse_cli_args(self) -> None:
        """Verify parsing of CLI arguments for database force-reseeding and project count."""
        import sys
        from unittest.mock import patch
        from app.main import parse_cli_args

        # Case 1: Long flags
        with patch.object(sys, "argv", ["streamlit_app.py", "--force-reseed", "--projects", "75"]):
            force, count = parse_cli_args()
            self.assertTrue(force)
            self.assertEqual(count, 75)

        # Streamlit options do not hide the application's project-count flag.
        with patch.object(sys, "argv", ["streamlit_app.py", "--server.port", "8501", "--projects", "30"]):
            force, count = parse_cli_args()
            self.assertFalse(force)
            self.assertEqual(count, 30)

        # Case 3: Defaults
        with patch.object(sys, "argv", ["streamlit_app.py"]):
            force, count = parse_cli_args()
            self.assertFalse(force)
            self.assertEqual(count, 0)


    def test_flatten_dynamic_attributes_preserves_raw_column(self) -> None:
        """Verify flatten_dynamic_attributes preserves dynamic_attributes column."""
        import pandas as pd

        df_proj = pd.DataFrame([
            {
                "id": 1,
                "name": "Test Alpha",
                "status": "Active",
                "planned_budget": 1000,
                "actual_budget": 500,
                "dynamic_attributes": {"code_courrier": "CC-001", "lot": "Lot A"},
            }
        ])
        df_params = pd.DataFrame([
            {"param_id": "code_courrier", "param_name": "Code Courrier", "param_type": "TEXT"},
            {"param_id": "lot", "param_name": "Lot", "param_type": "TEXT"},
        ])

        df_flat = flatten_dynamic_attributes(df_proj, df_params)
        self.assertIn("dynamic_attributes", df_flat.columns)
        self.assertIn("code_courrier", df_flat.columns)
        self.assertEqual(df_flat.iloc[0]["code_courrier"], "CC-001")
        self.assertEqual(df_flat.iloc[0]["lot"], "Lot A")
