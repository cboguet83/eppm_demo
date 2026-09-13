"""Explicit native migration and default portfolio/schema workflows."""

from pathlib import Path
import unittest

import pandas as pd
import psycopg
import pytest

from app.application.services.business_access import BusinessAccess
from app.infrastructure.postgresql.backup import PostgresTools
from app.main import create_schema_service
from app.operator_services import create_maintenance_service
from app.presentation.components import schema_frames
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access


class TestApplicationWorkflows(unittest.TestCase):
    """Exercise native schema installation and backed-up operator demo seeding."""

    @pytest.fixture(autouse=True)
    def native_setup(
        self, runtime: RuntimeResources, access: BusinessAccess,
        authorized: AuthorizedFixture, clients: PostgresTools, tmp_path: Path,
    ) -> None:
        """Start with an empty migrated business catalog and real native actors."""
        with psycopg.connect(authorized.setup.operator_url) as connection:
            connection.execute("DELETE FROM eppm.project")
        self.authorized = authorized
        self.resources = runtime
        self.access = access
        self.schema_repo = create_schema_service(runtime, access=access)
        self.maintenance = create_maintenance_service(
            authorized.setup.operator_url, backup_directory=tmp_path, archive_tools=clients,
        )

    def test_explicit_migrations_create_application_tables(self) -> None:
        """Verify the explicitly migrated PostgreSQL schema has all core tables."""

        with psycopg.connect(self.authorized.setup.operator_url) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='eppm'")
            tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {
            "schema_groups",
            "schema_parameters",
            "schema_param_options",
            "project",
            "project_task",
        }
        self.assertTrue(expected_tables.issubset(tables))


    def test_seed_default_data_populates_tables(self) -> None:
        """Verify default seeding inserts groups, params, options, projects, and milestones."""
        self.maintenance.seed_defaults()

        with psycopg.connect(self.authorized.setup.operator_url) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM eppm.schema_groups")
            group_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM eppm.schema_parameters")
            param_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM eppm.project")
            project_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM eppm.project_task")
            milestone_count = cursor.fetchone()[0]

        self.assertGreaterEqual(group_count, 2)
        self.assertGreaterEqual(param_count, 5)
        self.assertGreaterEqual(project_count, 3)
        self.assertGreaterEqual(milestone_count, 5)


    def test_database_seed_counts_include_projects_tasks_and_dependencies(self) -> None:
        """Verify the reseeding success summary uses persisted totals for all objects."""
        self.maintenance.seed_defaults()
        with psycopg.connect(self.authorized.setup.operator_url) as conn:
            conn.execute(
                """
                INSERT INTO eppm.task_dependencies
                    (task_id, predecessor_task_id, link_type, lag_days)
                VALUES (2, 1, 'FS', 0)
                """
            )
            conn.commit()

        counts = self.maintenance.counts()

        self.assertEqual(set(counts), {"projects", "tasks", "dependencies", "project_types", "property_values", "pools"})
        self.assertGreaterEqual(counts["projects"], 3)
        self.assertGreaterEqual(counts["tasks"], 5)
        self.assertEqual(counts["dependencies"], 15)
        self.assertEqual(counts["project_types"], 5)
        self.assertGreater(counts["property_values"], 0)


    def test_get_next_available_group_order(self) -> None:
        """Verify calculation of next available display order for schema groups."""
        self.assertEqual(create_schema_service(self.resources, access=self.access).get_next_available_group_order(), 1)

        self.maintenance.seed_defaults()
        self.assertEqual(create_schema_service(self.resources, access=self.access).get_next_available_group_order(), 6)


    def test_schema_group_edit_and_delete(self) -> None:
        """Verify editing an existing schema group and deleting it."""
        self.maintenance.seed_defaults()

        # Edit Group 1
        updated = self.schema_repo.update_group(1, "Updated Strategic Alignment", 10)
        self.assertTrue(updated)

        df = schema_frames.groups_frame(self.schema_repo.get_all_groups())
        row = df[df["id"] == 1].iloc[0]
        self.assertEqual(row["group_name"], "Updated Strategic Alignment")
        self.assertEqual(row["display_order"], 10)

        # Delete Group 1
        deleted = self.schema_repo.delete_group(1)
        self.assertTrue(deleted)

        df_after = schema_frames.groups_frame(self.schema_repo.get_all_groups())
        self.assertTrue(df_after[df_after["id"] == 1].empty)


    def test_create_ungrouped_parameter(self) -> None:
        """Verify creating a parameter without assigning it to any group (group_id is NULL)."""
        created = self.schema_repo.create_parameter("PRM_999", None, "Standalone Keyword", 'TAGS')
        self.assertTrue(created)

        params = schema_frames.parameters_frame(self.schema_repo.get_all_parameters())
        self.assertIn("PRM_999", params["param_id"].values)
        self.assertTrue(params.loc[params["param_id"] == "PRM_999", "group_id"].isna().values[0])
