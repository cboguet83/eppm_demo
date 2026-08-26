"""Unit and integration test suite for PPM Studio Pro."""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import pandas as pd

from app import (
    DB_NAME,
    PARAM_TYPE_ENUM,
    PARAM_TYPE_MULTI_ENUM,
    PARAM_TYPE_TEXT,
    PARAM_TYPE_URL,
    STATUS_DRAFT,
    STATUS_IN_PROGRESS,
    calculate_portfolio_metrics,
    flatten_dynamic_attributes,
    generate_param_id,
    get_db,
    init_db,
    load_full_schema,
    seed_default_data_if_empty,
)


class TestPPMStudio(unittest.TestCase):
    """Test suite for database operations, schema loading, project CRUD, and metrics."""

    def setUp(self) -> None:
        """Create a temporary database file for isolation."""
        self.test_dir = tempfile.mkdtemp()
        self.temp_db_path = os.path.join(self.test_dir, "test_ppm.db")

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_init_db_creates_tables(self) -> None:
        """Arrange, Act, Assert table creation in fresh SQLite database."""
        # Arrange & Act
        init_db(self.temp_db_path)

        # Assert
        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {
            "schema_groups",
            "schema_parameters",
            "schema_param_options",
            "projects",
            "project_milestones",
        }
        self.assertTrue(expected_tables.issubset(tables))

    def test_seed_default_data_populates_tables(self) -> None:
        """Verify default seeding inserts groups, params, options, projects, and milestones."""
        # Arrange
        init_db(self.temp_db_path)

        # Act
        seed_default_data_if_empty(self.temp_db_path)

        # Assert
        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM schema_groups")
            group_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM schema_parameters")
            param_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM projects")
            project_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM project_milestones")
            milestone_count = cursor.fetchone()[0]

        self.assertGreaterEqual(group_count, 2)
        self.assertGreaterEqual(param_count, 5)
        self.assertGreaterEqual(project_count, 5)
        self.assertGreaterEqual(milestone_count, 5)

    def test_seed_default_data_idempotent(self) -> None:
        """Verify running seed_default_data_if_empty multiple times does not duplicate records."""
        # Arrange
        init_db(self.temp_db_path)
        seed_default_data_if_empty(self.temp_db_path)

        # Act
        seed_default_data_if_empty(self.temp_db_path)

        # Assert
        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM projects")
            count = cursor.fetchone()[0]
        self.assertEqual(count, 5)

    def test_generate_param_id(self) -> None:
        """Verify incremental parameter ID generation."""
        # Arrange
        init_db(self.temp_db_path)

        # Act & Assert on empty
        next_id = generate_param_id(self.temp_db_path)
        self.assertEqual(next_id, "PRM_001")

        # Seed and check next
        seed_default_data_if_empty(self.temp_db_path)
        next_id_after_seed = generate_param_id(self.temp_db_path)
        self.assertEqual(next_id_after_seed, "PRM_006")

    def test_load_full_schema(self) -> None:
        """Verify loading schema dataframes."""
        # Arrange
        init_db(self.temp_db_path)
        seed_default_data_if_empty(self.temp_db_path)

        # Act
        groups, params, options = load_full_schema(self.temp_db_path)

        # Assert
        self.assertIsInstance(groups, pd.DataFrame)
        self.assertIsInstance(params, pd.DataFrame)
        self.assertIsInstance(options, pd.DataFrame)
        self.assertFalse(groups.empty)
        self.assertFalse(params.empty)
        self.assertFalse(options.empty)
        self.assertIn("group_name", groups.columns)
        self.assertIn("param_type", params.columns)

    def test_project_crud_and_cascade(self) -> None:
        """Verify adding, updating, and deleting a project cascades to milestones."""
        # Arrange
        init_db(self.temp_db_path)

        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            # Insert project
            cursor.execute(
                "INSERT INTO projects (id, name, status, planned_budget, actual_budget, dynamic_attributes) VALUES (?, ?, ?, ?, ?, ?)",
                ("PRJ-100", "Cloud Transformation", STATUS_DRAFT, 250000.0, 10000.0, json.dumps({"PRM_001": "P1 - Critical"})),
            )
            # Insert milestone
            cursor.execute(
                "INSERT INTO project_milestones (project_id, task_name, phase, start_date, end_date, progress_pct) VALUES (?, ?, ?, ?, ?, ?)",
                ("PRJ-100", "Infra Setup", "Phase 1", "2026-06-01", "2026-06-30", 50),
            )
            conn.commit()

        # Act: Update
        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE projects SET status = ? WHERE id = ?", (STATUS_IN_PROGRESS, "PRJ-100"))
            conn.commit()

        # Assert: Updated
        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM projects WHERE id = ?", ("PRJ-100",))
            self.assertEqual(cursor.fetchone()[0], STATUS_IN_PROGRESS)

        # Act: Delete project
        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM projects WHERE id = ?", ("PRJ-100",))
            conn.commit()

        # Assert: Project and milestones deleted via cascade
        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM projects WHERE id = ?", ("PRJ-100",))
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT COUNT(*) FROM project_milestones WHERE project_id = ?", ("PRJ-100",))
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_flatten_dynamic_attributes_empty(self) -> None:
        """Verify flatten_dynamic_attributes handles empty DataFrames safely."""
        # Arrange
        df_projects = pd.DataFrame()
        df_params = pd.DataFrame()

        # Act
        result = flatten_dynamic_attributes(df_projects, df_params)

        # Assert
        self.assertTrue(result.empty)

    def test_flatten_dynamic_attributes_success(self) -> None:
        """Verify flattening of JSON attributes into DataFrame columns."""
        # Arrange
        df_projects = pd.DataFrame([
            {
                "id": "PRJ-001",
                "name": "Project Alpha",
                "status": "In Progress",
                "planned_budget": 100000.0,
                "actual_budget": 50000.0,
                "dynamic_attributes": json.dumps({
                    "PRM_001": "Critical",
                    "PRM_002": "Engineering",
                    "PRM_003": ["Python", "Docker"],
                }),
            },
            {
                "id": "PRJ-002",
                "name": "Project Beta",
                "status": "Draft",
                "planned_budget": 50000.0,
                "actual_budget": 0.0,
                "dynamic_attributes": None,
            },
        ])
        df_params = pd.DataFrame([
            {"param_id": "PRM_001", "param_name": "Priority", "param_type": "ENUM"},
            {"param_id": "PRM_002", "param_name": "Department", "param_type": "TEXT"},
            {"param_id": "PRM_003", "param_name": "Tags", "param_type": "MULTI_ENUM"},
            {"param_id": "PRM_004", "param_name": "Link", "param_type": "URL"},
        ])

        # Act
        flattened = flatten_dynamic_attributes(df_projects, df_params)

        # Assert
        self.assertIn("PRM_001", flattened.columns)
        self.assertIn("PRM_002", flattened.columns)
        self.assertIn("PRM_003", flattened.columns)
        self.assertIn("PRM_004", flattened.columns)
        self.assertEqual(flattened.loc[flattened["id"] == "PRJ-001", "PRM_001"].values[0], "Critical")
        self.assertEqual(flattened.loc[flattened["id"] == "PRJ-001", "PRM_003"].values[0], ["Python", "Docker"])
        self.assertEqual(flattened.loc[flattened["id"] == "PRJ-002", "PRM_003"].values[0], [])

    def test_calculate_portfolio_metrics_empty(self) -> None:
        """Verify calculate_portfolio_metrics returns zeros for empty DataFrame."""
        # Arrange
        df_empty = pd.DataFrame()

        # Act
        metrics = calculate_portfolio_metrics(df_empty)

        # Assert
        self.assertEqual(metrics["total_planned"], 0.0)
        self.assertEqual(metrics["total_actual"], 0.0)
        self.assertEqual(metrics["variance"], 0.0)
        self.assertEqual(metrics["burn_rate"], 0.0)

    def test_calculate_portfolio_metrics_calculation(self) -> None:
        """Verify calculations for planned, actual, variance, and burn rate."""
        # Arrange
        df = pd.DataFrame([
            {"planned_budget": 100000.0, "actual_budget": 40000.0},
            {"planned_budget": 200000.0, "actual_budget": 110000.0},
        ])

        # Act
        metrics = calculate_portfolio_metrics(df)

        # Assert
        self.assertEqual(metrics["total_planned"], 300000.0)
        self.assertEqual(metrics["total_actual"], 150000.0)
        self.assertEqual(metrics["variance"], 150000.0)
        self.assertEqual(metrics["burn_rate"], 50.0)


if __name__ == "__main__":
    unittest.main()
