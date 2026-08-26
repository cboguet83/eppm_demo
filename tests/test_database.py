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
            "projects",
            "project_milestones",
        }
        self.assertTrue(expected.issubset(tables))

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
            cursor.execute("SELECT COUNT(*) FROM projects")
            projects_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM project_milestones")
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
            cursor.execute("SELECT COUNT(*) FROM projects")
            count = cursor.fetchone()[0]

        self.assertEqual(count, 3)


if __name__ == "__main__":
    unittest.main()
