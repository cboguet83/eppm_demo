"""Unit tests for database connection, schema initialization, and seeder."""

import os
import shutil
import tempfile
import unittest

from src.database.connection import get_db
from src.database.schema_init import init_db
from src.database.seeder import seed_default_data_if_empty


class TestDatabaseLayer(unittest.TestCase):
    """Test suite for SQLite database schema and seeding operations."""

    def setUp(self) -> None:
        """Arrange: Create isolated temporary directory for test database."""
        self.test_dir = tempfile.mkdtemp()
        self.temp_db_path = os.path.join(self.test_dir, "test_db.db")

    def tearDown(self) -> None:
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_init_db_creates_all_tables(self) -> None:
        """Verify init_db creates schema_groups, schema_parameters, options, projects, and milestones."""
        init_db(self.temp_db_path)

        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

        expected = {
            "schema_groups",
            "schema_parameters",
            "schema_param_options",
            "project",
            "project_task",
            "employee",
            "employee_calendar_exception",
        }
        self.assertTrue(expected.issubset(tables))

    def test_existing_employee_schema_migrates_occupation_percentage(self) -> None:
        """Verify an existing employee table receives the new availability fields safely."""
        with get_db(self.temp_db_path) as conn:
            conn.execute(
                """
                CREATE TABLE employee (
                    employee_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    firstname TEXT NOT NULL,
                    lastname TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    mobile TEXT DEFAULT '',
                    sigle TEXT DEFAULT '',
                    employee_code TEXT NOT NULL UNIQUE,
                    function_id INTEGER
                )
                """
            )
            conn.execute(
                """
                INSERT INTO employee (firstname, lastname, email, employee_code)
                VALUES ('Legacy', 'Employee', 'legacy@example.com', 'EMP-001')
                """
            )
            conn.commit()

        init_db(self.temp_db_path)

        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(employee)")
            columns = {row[1] for row in cursor.fetchall()}
            self.assertIn("occupation_percentage", columns)
            cursor.execute("SELECT occupation_percentage FROM employee WHERE employee_code = 'EMP-001'")
            self.assertEqual(cursor.fetchone()[0], 100.0)
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'employee_calendar_exception'"
            )
            self.assertIsNotNone(cursor.fetchone())

    def test_seed_default_data_populates_records(self) -> None:
        """Verify seed_default_data_if_empty seeds initial taxonomy and demo projects."""
        init_db(self.temp_db_path)
        seed_default_data_if_empty(self.temp_db_path)

        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM schema_groups")
            groups_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM schema_parameters")
            params_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM project")
            projects_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM project_task")
            milestones_count = cursor.fetchone()[0]

        self.assertGreaterEqual(groups_count, 2)
        self.assertGreaterEqual(params_count, 5)
        self.assertGreaterEqual(projects_count, 3)
        self.assertGreaterEqual(milestones_count, 5)

    def test_seed_is_idempotent(self) -> None:
        """Verify running seed_default_data_if_empty multiple times does not duplicate data."""
        init_db(self.temp_db_path)
        seed_default_data_if_empty(self.temp_db_path)
        seed_default_data_if_empty(self.temp_db_path)

        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM project")
            count = cursor.fetchone()[0]

        self.assertEqual(count, 5)

    def test_seed_creates_all_categories_parameters_and_enums(self) -> None:
        """Verify seeded categories, 30 parameters, all discrete enums, and project manager FKs."""
        import json
        init_db(self.temp_db_path)
        seed_default_data_if_empty(self.temp_db_path)

        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()

            # 1. Verify 5 Groups
            cursor.execute("SELECT group_name FROM schema_groups ORDER BY display_order")
            groups = [r[0] for r in cursor.fetchall()]
            expected_groups = ["basic info", "scoping", "localization", "useful links", "classification"]
            self.assertEqual(groups, expected_groups)

            # 2. Verify 29 Parameters (status removed as dynamic attribute)
            cursor.execute("SELECT param_id, param_name, param_type, mandatory, alias FROM schema_parameters ORDER BY param_id")
            params = cursor.fetchall()
            self.assertEqual(len(params), 31)

            param_names = {r[1] for r in params}
            expected_param_names = {
                "code courrier", "benefits", "acceptance_ctriteria", "scope", "out_of_scope",
                "risks", "stakeholders", "interfaces", "description", "commentaire",
                "start_date", "stop_Date", "lot", "phase",
                "code_station", "code_line", "lat", "long", "section",
                "station", "pk_start", "pk_stop", "acc_link", "pb_link",
                "orga_link", "strategic_priority", "category", "category_tags", "complexity", "public_url", "delivery_channels"
            }
            self.assertEqual(param_names, expected_param_names)

            # All parameters default to mandatory=False (0)
            self.assertEqual({r[0] for r in params if r[3]}, {"PRM_011"})

            # Check alias for code_line
            code_line_param = next(r for r in params if r[1] == "code_line")
            self.assertEqual(code_line_param[4], "code ligne")

            # 3. Verify Enums in schema_param_options
            cursor.execute("SELECT option_value FROM schema_param_options WHERE param_id='PRM_008' ORDER BY display_order")
            phase_opts = [r[0] for r in cursor.fetchall()]
            self.assertEqual(phase_opts, ["FAI", "APS", "APD1", "APD2", "EXE", "CHA", "DEF", "N/A"])

            cursor.execute("SELECT option_value FROM schema_param_options WHERE param_id='PRM_017' ORDER BY display_order")
            line_opts = [r[0] for r in cursor.fetchall()]
            expected_lines = ["1", "1a", "1b", "2b", "3", "4", "5", "6", "6a", "6b", "6c", "6d", "6e", "6f", "6g", "6h", "6j", "6k", "7"]
            self.assertEqual(line_opts, expected_lines)

            cursor.execute("SELECT option_value FROM schema_param_options WHERE param_id='PRM_030' ORDER BY display_order")
            complexity_opts = [r[0] for r in cursor.fetchall()]
            self.assertEqual(complexity_opts, ["High", "Medium", "Low"])

            cursor.execute("SELECT option_value FROM schema_param_options WHERE param_id='PRM_028' ORDER BY display_order")
            category_opts = [r[0] for r in cursor.fetchall()]
            self.assertEqual(category_opts, ["categ1", "categ2", "categ3"])

            cursor.execute("SELECT option_value FROM schema_param_options WHERE param_id='PRM_027' ORDER BY display_order")
            strat_opts = [r[0] for r in cursor.fetchall()]
            self.assertEqual(strat_opts, ["Critical", "High", "Medium", "Low"])

            cursor.execute("SELECT COUNT(*) FROM schema_param_options WHERE param_id='PRM_016'")
            station_count = cursor.fetchone()[0]
            self.assertGreaterEqual(station_count, 120)

            # Five project types, with only their effective custom properties.
            from src.database.property_store import effective_template, read_values
            cursor.execute("SELECT id, name, function_id, project_type_id FROM project")
            projects = cursor.fetchall()
            self.assertEqual(len(projects), 5)
            values = read_values(conn)
            for p_id, p_name, func_id, type_id in projects:
                self.assertIsNotNone(func_id)
                self.assertGreater(func_id, 0)
                self.assertEqual(set(values[p_id]), {p["param_id"] for p in effective_template(conn, type_id)})
    def test_seed_force_reseed_resets_database(self) -> None:
        """Verify that passing force=True wipes existing custom records and restores seed data."""
        init_db(self.temp_db_path)
        seed_default_data_if_empty(self.temp_db_path)

        # Insert custom dummy data that should be wiped on force re-seed
        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO project (id, name, status, planned_budget, actual_budget) VALUES (999, 'Dummy Custom Project', 'Draft', 1000, 500)"
            )
            cursor.execute(
                "INSERT INTO schema_groups (id, group_name, display_order) VALUES (999, 'custom_group', 999)"
            )
            conn.commit()

        # Verify custom data is present before force reseed
        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM project WHERE id = 999")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT COUNT(*) FROM schema_groups WHERE id = 999")
            self.assertEqual(cursor.fetchone()[0], 1)

        # Force reseed
        seed_default_data_if_empty(self.temp_db_path, force=True)

        # Verify custom data is wiped and standard seed data is cleanly restored
        with get_db(self.temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM project WHERE id = 999")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT COUNT(*) FROM schema_groups WHERE id = 999")
            self.assertEqual(cursor.fetchone()[0], 0)

            cursor.execute("SELECT COUNT(*) FROM project")
            self.assertEqual(cursor.fetchone()[0], 5)
            cursor.execute("SELECT COUNT(*) FROM schema_groups")
            self.assertEqual(cursor.fetchone()[0], 5)
            cursor.execute("SELECT COUNT(*) FROM schema_parameters")
            self.assertEqual(cursor.fetchone()[0], 31)
            cursor.execute("SELECT COUNT(*) FROM function")
            self.assertEqual(cursor.fetchone()[0], 60)
            cursor.execute("SELECT COUNT(*) FROM employee")
            self.assertEqual(cursor.fetchone()[0], 50)
            cursor.execute("SELECT COUNT(*) FROM resource_pool")
            self.assertEqual(cursor.fetchone()[0], 103)
            cursor.execute("SELECT COUNT(*) FROM resource_pool_group")
            self.assertEqual(cursor.fetchone()[0], 31)


if __name__ == "__main__":
    unittest.main()
