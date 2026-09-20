"""Independent native schema/default-catalog contracts retained from the demo."""

from pathlib import Path
import unittest

import psycopg
import pytest

from app.infrastructure.postgresql.backup import PostgresTools
from app.infrastructure.postgresql.migration import migrate
from app.operator_services import create_maintenance_service
from tests.postgresql.conftest import PostgreSQLFixture


class TestDatabaseContracts(unittest.TestCase):
    """Exercise explicit migrated storage and backed-up default seeding."""

    @pytest.fixture(autouse=True)
    def native_setup(self, pg_database: PostgreSQLFixture, clients: PostgresTools, tmp_path: Path) -> None:
        """Use a unique database and real archive clients for every test."""
        self.setup = pg_database
        self.maintenance = create_maintenance_service(pg_database.operator_url, backup_directory=tmp_path, archive_tools=clients)

    def test_operator_migrations_create_all_application_tables(self) -> None:
        """Verify explicit migrations install the project, directory and calendar tables."""
        migrate(self.setup.operator_url)

        with psycopg.connect(self.setup.operator_url) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='eppm'")
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

    def test_native_employee_availability_defaults_survive_migration_reentry(self) -> None:
        """Verify fresh native availability fields and idempotent operator reentry."""
        with psycopg.connect(self.setup.operator_url) as connection:
            connection.execute("INSERT INTO eppm.employee(firstname,lastname,email) VALUES('Native','Employee','native@example.test')")
        migrate(self.setup.operator_url)
        with psycopg.connect(self.setup.operator_url) as connection:
            self.assertEqual(connection.execute("SELECT occupation_percentage FROM eppm.employee WHERE email='native@example.test'").fetchone()[0], 100)
            self.assertIsNotNone(connection.execute("SELECT to_regclass('eppm.employee_calendar_exception')").fetchone()[0])

    def test_seed_default_data_populates_records(self) -> None:
        """Verify seed_default_data_if_empty seeds initial taxonomy and demo projects."""
        migrate(self.setup.operator_url)
        self.maintenance.seed_defaults()

        with psycopg.connect(self.setup.operator_url) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM eppm.schema_groups")
            groups_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM eppm.schema_parameters")
            params_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM eppm.project")
            projects_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM eppm.project_task")
            milestones_count = cursor.fetchone()[0]

        self.assertGreaterEqual(groups_count, 2)
        self.assertGreaterEqual(params_count, 5)
        self.assertGreaterEqual(projects_count, 3)
        self.assertGreaterEqual(milestones_count, 5)

    def test_seed_is_idempotent(self) -> None:
        """Verify running seed_default_data_if_empty multiple times does not duplicate data."""
        migrate(self.setup.operator_url)
        self.maintenance.seed_defaults()
        self.maintenance.seed_defaults()

        with psycopg.connect(self.setup.operator_url) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM eppm.project")
            count = cursor.fetchone()[0]

        self.assertEqual(count, 5)

    def test_seed_creates_all_categories_parameters_and_enums(self) -> None:
        """Verify categories, 30 parameters, native priority and manager references."""
        migrate(self.setup.operator_url)
        self.maintenance.seed_defaults()

        with psycopg.connect(self.setup.operator_url) as conn:
            cursor = conn.cursor()

            # 1. Verify 5 Groups
            cursor.execute("SELECT group_name FROM eppm.schema_groups ORDER BY display_order")
            groups = [r[0] for r in cursor.fetchall()]
            expected_groups = ["basic info", "scoping", "localization", "useful links", "classification"]
            self.assertEqual(groups, expected_groups)

            # Verify all 30 configured parameters independently of seed constants.
            cursor.execute("SELECT param_id, param_name, param_type, mandatory, alias FROM eppm.schema_parameters ORDER BY param_id")
            params = cursor.fetchall()
            self.assertEqual(len(params), 30)

            param_names = {r[1] for r in params}
            expected_param_names = {
                "code courrier", "benefits", "acceptance_ctriteria", "scope", "out_of_scope",
                "risks", "stakeholders", "interfaces", "description", "commentaire",
                "start_date", "stop_Date", "lot", "phase",
                "code_station", "code_line", "lat", "long", "section",
                "station", "pk_start", "pk_stop", "acc_link", "pb_link",
                "orga_link", "category", "category_tags", "complexity", "public_url", "delivery_channels"
            }
            self.assertEqual(param_names, expected_param_names)

            # Only the configured scope property is required at catalog level.
            self.assertEqual({r[0] for r in params if r[3]}, {"PRM_011"})

            # Check alias for code_line
            code_line_param = next(r for r in params if r[1] == "code_line")
            self.assertEqual(code_line_param[4], "code ligne")

            # 3. Verify Enums in schema_param_options
            cursor.execute("SELECT option_value FROM eppm.schema_param_options WHERE param_id='PRM_008' ORDER BY display_order")
            phase_opts = [r[0] for r in cursor.fetchall()]
            self.assertEqual(phase_opts, ["FAI", "APS", "APD1", "APD2", "EXE", "CHA", "DEF", "N/A"])

            cursor.execute("SELECT option_value FROM eppm.schema_param_options WHERE param_id='PRM_017' ORDER BY display_order")
            line_opts = [r[0] for r in cursor.fetchall()]
            expected_lines = ["1", "1a", "1b", "2b", "3", "4", "5", "6", "6a", "6b", "6c", "6d", "6e", "6f", "6g", "6h", "6j", "6k", "7"]
            self.assertEqual(line_opts, expected_lines)

            cursor.execute("SELECT option_value FROM eppm.schema_param_options WHERE param_id='PRM_030' ORDER BY display_order")
            complexity_opts = [r[0] for r in cursor.fetchall()]
            self.assertEqual(complexity_opts, ["High", "Medium", "Low"])

            cursor.execute("SELECT option_value FROM eppm.schema_param_options WHERE param_id='PRM_028' ORDER BY display_order")
            category_opts = [r[0] for r in cursor.fetchall()]
            self.assertEqual(category_opts, ["categ1", "categ2", "categ3"])

            cursor.execute("SELECT label FROM eppm.strategic_priority_translation t JOIN eppm.strategic_priority p ON p.id=t.strategic_priority_id WHERE locale='en' ORDER BY display_order")
            strat_opts = [r[0] for r in cursor.fetchall()]
            self.assertEqual(strat_opts, ["Strategic", "High", "Medium", "Low"])

            cursor.execute("SELECT COUNT(*) FROM eppm.schema_param_options WHERE param_id='PRM_016'")
            station_count = cursor.fetchone()[0]
            self.assertGreaterEqual(station_count, 120)

            # Five project types, with only their effective custom properties.
            from app.infrastructure.postgresql.property_store import read_values
            from app.infrastructure.postgresql.projects import PostgresProjectStore
            cursor.execute("SELECT id, name, function_id, project_type_id FROM eppm.project")
            projects = cursor.fetchall()
            self.assertEqual(len(projects), 5)
            values = read_values(conn)
            for p_id, p_name, func_id, type_id in projects:
                self.assertIsNotNone(func_id)
                self.assertGreater(func_id, 0)
                self.assertEqual(set(values[p_id]), {p["param_id"] for p in PostgresProjectStore(conn).template(type_id)})
    def test_seed_force_reseed_resets_database(self) -> None:
        """Verify that passing force=True wipes existing custom records and restores seed data."""
        migrate(self.setup.operator_url)
        self.maintenance.seed_defaults()

        # Insert custom dummy data that should be wiped on force re-seed
        with psycopg.connect(self.setup.operator_url) as conn:
            cursor = conn.cursor()
            seeded_pools = cursor.execute(
                "SELECT pool.name,parent.name FROM eppm.resource_pool pool "
                "LEFT JOIN eppm.resource_pool parent ON parent.id=pool.parent_pool_id ORDER BY pool.name"
            ).fetchall()
            cursor.execute(
                "INSERT INTO eppm.project (id, name, status) VALUES (999, 'Dummy Custom Project', 'Draft')"
            )
            cursor.execute(
                "INSERT INTO eppm.schema_groups (id, group_name, display_order) VALUES (999, 'custom_group', 999)"
            )
            conn.commit()

        # Verify custom data is present before force reseed
        with psycopg.connect(self.setup.operator_url) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM eppm.project WHERE id = 999")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT COUNT(*) FROM eppm.schema_groups WHERE id = 999")
            self.assertEqual(cursor.fetchone()[0], 1)

        # Force reseed
        self.maintenance.seed_defaults(force=True)

        # Verify custom data is wiped and standard seed data is cleanly restored
        with psycopg.connect(self.setup.operator_url) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM eppm.project WHERE id = 999")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT COUNT(*) FROM eppm.schema_groups WHERE id = 999")
            self.assertEqual(cursor.fetchone()[0], 0)

            cursor.execute("SELECT COUNT(*) FROM eppm.project")
            self.assertEqual(cursor.fetchone()[0], 5)
            cursor.execute("SELECT COUNT(*) FROM eppm.schema_groups")
            self.assertEqual(cursor.fetchone()[0], 5)
            cursor.execute("SELECT COUNT(*) FROM eppm.schema_parameters")
            self.assertEqual(cursor.fetchone()[0], 30)
            cursor.execute("SELECT COUNT(*) FROM eppm.function")
            self.assertEqual(cursor.fetchone()[0], 60)
            cursor.execute("SELECT COUNT(*) FROM eppm.employee")
            self.assertEqual(cursor.fetchone()[0], 50)
            cursor.execute(
                "SELECT pool.name,parent.name FROM eppm.resource_pool pool "
                "LEFT JOIN eppm.resource_pool parent ON parent.id=pool.parent_pool_id ORDER BY pool.name"
            )
            self.assertEqual(cursor.fetchall(), seeded_pools)
