"""Unit tests for Business Logic Services."""

import io
import json
import os
import shutil
import tempfile
import unittest

import pandas as pd

from src.database.schema_init import init_db
from src.models.constants import PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS, PARAM_TYPE_TEXT
from src.repositories.schema_repo import SchemaRepository
from src.services.milestone_service import MilestoneService
from src.services.portfolio_service import PortfolioService
from src.services.schema_service import SchemaService


class TestServices(unittest.TestCase):
    """Test suite for PortfolioService, SchemaService, and MilestoneService."""

    def setUp(self) -> None:
        """Arrange: Create isolated temporary directory for test database."""
        self.test_dir = tempfile.mkdtemp()
        self.temp_db_path = os.path.join(self.test_dir, "test_services.db")
        init_db(self.temp_db_path)

    def tearDown(self) -> None:
        """Clean up temporary test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_calculate_portfolio_metrics(self) -> None:
        """Verify calculations for planned, actual, variance, and burn rate."""
        df = pd.DataFrame([
            {"planned_budget": 100000.0, "actual_budget": 40000.0},
            {"planned_budget": 200000.0, "actual_budget": 110000.0},
        ])
        metrics = PortfolioService.calculate_portfolio_metrics(df)

        self.assertEqual(metrics.total_projects, 2)
        self.assertEqual(metrics.total_planned, 300000.0)
        self.assertEqual(metrics.total_actual, 150000.0)
        self.assertEqual(metrics.variance, 150000.0)
        self.assertEqual(metrics.burn_rate, 50.0)

    def test_calculate_portfolio_metrics_empty(self) -> None:
        """Verify metrics for empty DataFrame."""
        metrics = PortfolioService.calculate_portfolio_metrics(pd.DataFrame())
        self.assertEqual(metrics.total_projects, 0)
        self.assertEqual(metrics.total_planned, 0.0)
        self.assertEqual(metrics.total_actual, 0.0)

    def test_flatten_dynamic_attributes(self) -> None:
        """Verify flattening dynamic JSON attributes into DataFrame columns."""
        df_projects = pd.DataFrame([
            {
                "id": "PRJ-001",
                "name": "Alpha",
                "dynamic_attributes": json.dumps({
                    "PRM_001": ["Python", "Docker"],
                    "PRM_002": "Single",
                }),
            },
            {
                "id": "PRJ-002",
                "name": "Beta",
                "dynamic_attributes": json.dumps({
                    "PRM_001": "SingleTag",
                }),
            },
        ])
        df_params = pd.DataFrame([
            {"param_id": "PRM_001", "param_name": "Tags", "param_type": PARAM_TYPE_TAGS},
            {"param_id": "PRM_002", "param_name": "Text", "param_type": PARAM_TYPE_TEXT},
        ])

        flattened = PortfolioService.flatten_dynamic_attributes(df_projects, df_params)

        self.assertIn("PRM_001", flattened.columns)
        self.assertIn("PRM_002", flattened.columns)
        self.assertEqual(flattened.loc[flattened["id"] == "PRJ-001", "PRM_001"].values[0], ["Python", "Docker"])
        self.assertEqual(flattened.loc[flattened["id"] == "PRJ-002", "PRM_001"].values[0], ["SingleTag"])

    def test_schema_service_generate_param_id(self) -> None:
        """Verify sequential parameter ID generation."""
        repo = SchemaRepository(self.temp_db_path)
        pid1 = SchemaService.generate_param_id(self.temp_db_path)
        self.assertEqual(pid1, "PRM_001")

        repo.create_parameter("PRM_001", None, "Param 1", PARAM_TYPE_TEXT)
        pid2 = SchemaService.generate_param_id(self.temp_db_path)
        self.assertEqual(pid2, "PRM_002")

    def test_schema_service_next_available_group_order(self) -> None:
        """Verify next available group order computation."""
        repo = SchemaRepository(self.temp_db_path)
        self.assertEqual(SchemaService.get_next_available_group_order(self.temp_db_path), 1)

        repo.create_group("Group A", 1)
        repo.create_group("Group B", 2)
        self.assertEqual(SchemaService.get_next_available_group_order(self.temp_db_path), 3)

    def test_milestone_service_parse_csv(self) -> None:
        """Verify parsing valid step/milestone CSV data including predecessor_id and 0-duration milestones."""
        csv_data = io.StringIO(
            "task_name,phase,start_date,end_date,progress_pct,predecessor_id\n"
            "Deploy API,Phase 1,2026-01-01,2026-01-15,100,\n"
            "Milestone Gate 1,Phase 1,2026-01-15,2026-01-15,100,1\n"
            "Build UI,Phase 2,2026-01-16,2026-02-15,50,2\n"
        )
        parsed = MilestoneService.parse_csv(csv_data, "PRJ-999")
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0]["project_id"], "PRJ-999")
        self.assertEqual(parsed[0]["task_name"], "Deploy API")
        self.assertIsNone(parsed[0]["predecessor_id"])
        self.assertEqual(parsed[1]["start_date"], parsed[1]["end_date"])
        self.assertEqual(parsed[1]["predecessor_id"], 1)

    def test_milestone_service_parse_csv_invalid_dates(self) -> None:
        """Verify error raised when end_date is before start_date."""
        invalid_csv = io.StringIO(
            "task_name,phase,start_date,end_date,progress_pct\n"
            "Invalid Task,Phase 1,2026-02-15,2026-01-01,0\n"
        )
        with self.assertRaises(ValueError):
            MilestoneService.parse_csv(invalid_csv, "PRJ-999")

    def test_milestone_service_parse_csv_missing_cols(self) -> None:
        """Verify error raised on missing required columns."""
        invalid_csv = io.StringIO("phase,start_date\nPhase 1,2026-01-01\n")
        with self.assertRaises(ValueError):
            MilestoneService.parse_csv(invalid_csv, "PRJ-999")


if __name__ == "__main__":
    unittest.main()
