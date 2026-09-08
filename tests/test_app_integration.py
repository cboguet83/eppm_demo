"""Integration tests for PPM Studio Pro."""

import os
import shutil
import tempfile
import unittest

from src.database.connection import get_db
from src.database.schema_init import init_db
from src.database.seeder import seed_default_data_if_empty
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.schema_repo import SchemaRepository
from src.services.portfolio_service import PortfolioService


class TestIntegration(unittest.TestCase):
    """End-to-end workflow integration tests across repositories and services."""

    def setUp(self) -> None:
        """Arrange: Isolated test database initialized with seed data."""
        self.test_dir = tempfile.mkdtemp()
        self.temp_db_path = os.path.join(self.test_dir, "test_integration.db")
        init_db(self.temp_db_path)
        seed_default_data_if_empty(self.temp_db_path)

        self.schema_repo = SchemaRepository(self.temp_db_path)
        self.project_repo = ProjectRepository(self.temp_db_path)
        self.milestone_repo = MilestoneRepository(self.temp_db_path)

    def tearDown(self) -> None:
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_full_portfolio_lifecycle(self) -> None:
        """Verify full lifecycle: create schema -> create project -> add milestone -> calculate KPIs -> delete."""
        # 1. Add new schema group and parameter
        grp_id = self.schema_repo.create_group("Cloud Operations", 10)
        self.schema_repo.create_parameter("PRM_CLD", grp_id, "Cloud Target", "ENUM")
        self.schema_repo.add_option("PRM_CLD", "GCP", 1)
        self.schema_repo.add_option("PRM_CLD", "Azure", 2)

        # 2. Add new project using the dynamic parameter
        new_pid = 101
        self.project_repo.create_project(
            project_id=new_pid,
            name="Cloud Migration",
            status="In Progress",
            planned_budget=100000.0,
            actual_budget=40000.0,
            dynamic_attributes={"PRM_CLD": "GCP"},
        )

        # 3. Add milestones
        self.milestone_repo.create_milestone(
            project_id=new_pid,
            task_name="Assessment",
            phase="Phase 1",
            start_date="2026-01-01",
            end_date="2026-02-01",
            progress_pct=100,
        )

        # 4. Fetch projects and verify metrics & attribute flattening
        df_projects = self.project_repo.get_all_projects()
        df_params = self.schema_repo.get_all_parameters()
        metrics = PortfolioService.calculate_portfolio_metrics(df_projects)
        df_flattened = PortfolioService.flatten_dynamic_attributes(df_projects, df_params)

        self.assertIn("PRM_CLD", df_flattened.columns)
        self.assertEqual(
            df_flattened.loc[df_flattened["id"] == new_pid, "PRM_CLD"].values[0],
            "GCP",
        )
        self.assertGreaterEqual(metrics.total_projects, 4)

        # 5. Clean up project
        self.project_repo.delete_project(new_pid)
        self.assertFalse(self.project_repo.exists(new_pid))

    def test_all_src_modules_import_cleanly(self) -> None:
        """Verify that all src modules and their type annotations import without NameError."""
        import importlib
        import pkgutil
        import src

        for module_info in pkgutil.walk_packages(src.__path__, prefix="src."):
            mod = importlib.import_module(module_info.name)
            self.assertIsNotNone(mod)

    def test_no_direct_app_sidebar_nav_assignment_in_views(self) -> None:
        """Verify that presentation views do not write directly to st.session_state['app_sidebar_nav'].

        Direct writes to a rendered widget key trigger StreamlitWidgetAlreadyInstantiatedError.
        All programmatic transitions must use st.session_state['nav_redirect'].
        """
        import re
        from pathlib import Path

        views_dir = Path("src/views")
        pattern = re.compile(r'st\.session_state\[(["\'])app_sidebar_nav\1\]\s*=')

        violations = []
        for py_file in views_dir.glob("*.py"):
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
        from src.views.portfolio_view import ALLOWED_DYNAMIC_PARAMS

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

    def test_portfolio_table_payload_hides_id_but_retains_row_identity(self) -> None:
        """The custom table payload must not expose the project-code column."""
        import pandas as pd

        from src.views.portfolio_view import _build_portfolio_table_rows

        frame = pd.DataFrame([
            {"id": 42, "name": "Apollo", "status": "Draft", "tags": ["Strategic"]},
        ])

        rows = _build_portfolio_table_rows(frame, ["name", "status"])

        self.assertEqual(rows, [{"name": "Apollo", "status": "Draft", "project_id": 42}])
        self.assertNotIn("id", rows[0])

    def test_portfolio_row_click_is_applied_before_table_render(self) -> None:
        """The component event must synchronize the stable project ID before mounting."""
        import streamlit as st

        from src.views.portfolio_view import _sync_portfolio_project_selection

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
        from app import parse_cli_args

        # Case 1: Long flags
        with patch.object(sys, "argv", ["app.py", "--force-reseed", "--projects", "75"]):
            force, count = parse_cli_args()
            self.assertTrue(force)
            self.assertEqual(count, 75)

        # Case 2: Short flags
        with patch.object(sys, "argv", ["app.py", "-f", "-n", "30"]):
            force, count = parse_cli_args()
            self.assertTrue(force)
            self.assertEqual(count, 30)

        # Case 3: Defaults
        with patch.object(sys, "argv", ["app.py"]):
            force, count = parse_cli_args()
            self.assertFalse(force)
            self.assertEqual(count, 0)

    def test_flatten_dynamic_attributes_preserves_raw_column(self) -> None:
        """Verify PortfolioService.flatten_dynamic_attributes preserves dynamic_attributes column."""
        import json
        import pandas as pd

        df_proj = pd.DataFrame([
            {
                "id": 1,
                "name": "Test Alpha",
                "status": "Active",
                "planned_budget": 1000.0,
                "actual_budget": 500.0,
                "dynamic_attributes": json.dumps({"code_courrier": "CC-001", "lot": "Lot A"}),
            }
        ])
        df_params = pd.DataFrame([
            {"param_id": "code_courrier", "param_name": "Code Courrier", "param_type": "TEXT"},
            {"param_id": "lot", "param_name": "Lot", "param_type": "TEXT"},
        ])

        df_flat = PortfolioService.flatten_dynamic_attributes(df_proj, df_params)
        self.assertIn("dynamic_attributes", df_flat.columns)
        self.assertIn("code_courrier", df_flat.columns)
        self.assertEqual(df_flat.iloc[0]["code_courrier"], "CC-001")
        self.assertEqual(df_flat.iloc[0]["lot"], "Lot A")


if __name__ == "__main__":
    unittest.main()
