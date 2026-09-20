"""Native template workflows, typed values and explicit operator reentry."""

from app.main import create_project_service
from app.main import create_schema_service

from app.presentation.components.planning_catalog import flatten_dynamic_attributes

from app.presentation.components import project_type_frames
from app.presentation.components import schema_frames
import pandas as pd


import psycopg
import pytest

from app.application.ports.maintenance import SeedRequest
from app.application.services.business_access import BusinessAccess
from app.infrastructure.postgresql.backup import PostgresTools
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access
import unittest
from pathlib import Path

from app.infrastructure.postgresql.property_store import read_values
from app.infrastructure.postgresql.projects import PostgresProjectStore
from app.domain.projects.project import prepare_project_values
from app.main import create_project_type_service
from app.operator_services import create_maintenance_service


class ProjectTypesTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def native_setup(
        self, authorized: AuthorizedFixture, runtime: RuntimeResources,
        access: BusinessAccess, tmp_path: Path, clients: PostgresTools,
    ) -> None:
        """Exercise real services with separate backed-up operator commands."""
        self.setup, self.resources, self.access = authorized.setup, runtime, access
        with psycopg.connect(self.setup.operator_url) as connection:
            connection.execute('DELETE FROM eppm.project')
        self.types = create_project_type_service(runtime, access=access)
        self.schema = create_schema_service(runtime, access=access)
        self.projects = create_project_service(runtime, access=access)
        self.maintenance = create_maintenance_service(
            self.setup.operator_url, backup_directory=tmp_path, archive_tools=clients,
        )

    def test_all_future_types_and_selected_membership(self):
        a = self.types.create_type("A")
        self.schema.create_parameter("global", None, "Shared", "TEXT")
        self.schema.create_parameter("local", None, "Local", "TEXT", applies_to_all=False, project_type_ids=[a])
        b = self.types.create_type("B")
        self.assertEqual(set([item['param_id'] for item in self.types.get_template(a)]), {"global", "local"})
        self.assertEqual(set([item['param_id'] for item in self.types.get_template(b)]), {"global"})
        with self.assertRaises(ValueError):
            self.schema.create_parameter("invalid", None, "Bad", "TEXT", applies_to_all=False)
        self.assertNotIn("invalid", set(schema_frames.parameters_frame(self.schema.get_all_parameters()).param_id))
        with self.assertRaises(ValueError):
            self.types.delete_type(a)

    def test_required_inheritance_and_overrides(self):
        a = self.types.create_type("A")
        self.schema.create_parameter("p", None, "Title", "TEXT", mandatory=True)
        with self.assertRaises(ValueError):
            self.projects.create_project(name="Missing")
        self.types.save_rule(a, "p", False)
        self.projects.create_project(name="Optional", project_type_id=a)
        self.schema.update_parameter("p", None, "Title", "TEXT", mandatory=False)
        self.types.save_rule(a, "p", True)
        self.projects.create_project(name="Inherited optional")
        with self.assertRaises(ValueError):
            self.projects.create_project(name="Explicitly required", project_type_id=a)
        self.assertEqual(len(pd.DataFrame(create_project_service(self.resources, access=self.access).get_planning_catalog(tuple(parameter.param_id for parameter in create_schema_service(self.resources, access=self.access).get_all_parameters())))), 2)

    def test_defaults_only_creation_preserve_clear_and_edit(self):
        a = self.types.create_type("A")
        self.schema.create_parameter("p", None, "Value", "TEXT")
        self.types.save_rule(a, "p", has_default=True, default_value="Initial")
        pid = self.projects.create_project(name="Defaulted", project_type_id=a)
        self.assertEqual(self.projects.get_project_by_id(pid).dynamic_attributes, {"p": "Initial"})
        clear = self.projects.create_project(name="Cleared", project_type_id=a, dynamic_attributes={"p": ""})
        self.assertEqual(self.projects.get_project_by_id(clear).dynamic_attributes, {"p": ""})
        self.types.save_rule(a, "p", has_default=True, default_value="Changed")
        self.projects.update_project(pid, "Edited", "Draft", {})
        self.assertEqual(self.projects.get_project_by_id(pid).dynamic_attributes, {"p": "Initial"})
        other = self.projects.create_project(name="Other")
        self.projects.update_project(other, "Switched", "Draft", {}, project_type_id=a)
        self.assertEqual(self.projects.get_project_by_id(other).dynamic_attributes, {})

    def test_inactive_values_retained_hidden_and_restored(self):
        a = self.types.create_type("A")
        self.schema.create_parameter("p", None, "Secret detail", "TEXT", mandatory=True, applies_to_all=False, project_type_ids=[a])
        pid = self.projects.create_project(name="Project", project_type_id=a, dynamic_attributes={"p": "Keep me"})
        self.projects.update_project(pid, "Project", "Draft", {}, project_type_id=1)
        self.assertEqual(self.projects.get_project_by_id(pid).dynamic_attributes, {"p": "Keep me"})
        rows = pd.DataFrame(create_project_service(self.resources, access=self.access).get_planning_catalog(tuple(parameter.param_id for parameter in create_schema_service(self.resources, access=self.access).get_all_parameters())))
        self.assertEqual(rows.iloc[0].dynamic_attributes, {})
        flattened = flatten_dynamic_attributes(rows, schema_frames.parameters_frame(self.schema.get_all_parameters()))
        self.assertIsNone(flattened.iloc[0]["p"])
        with self.assertRaises(ValueError):
            self.projects.update_project(pid, "Should roll back", "Draft", {"p": "No"})
        self.assertEqual(self.projects.get_project_by_id(pid).name, "Project")
        self.projects.update_project(pid, "Project", "Draft", {}, project_type_id=a)
        self.assertEqual(pd.DataFrame(create_project_service(self.resources, access=self.access).get_planning_catalog(tuple(parameter.param_id for parameter in create_schema_service(self.resources, access=self.access).get_all_parameters()))).iloc[0].dynamic_attributes, {"p": "Keep me"})
        self.types.set_applicability("p", False, [1])
        self.assertEqual(pd.DataFrame(create_project_service(self.resources, access=self.access).get_planning_catalog(tuple(parameter.param_id for parameter in create_schema_service(self.resources, access=self.access).get_all_parameters()))).iloc[0].dynamic_attributes, {})

    def test_all_property_types_and_empty_distinctions(self):
        values = {"TEXT": "Text", "NUMBER": 0, "DATE": "2026-09-08", "ENUM": "A", "MULTI_ENUM": ["B", "A"], "TAGS": ["free", "tag"], "URL": "https://example.org", "HYPERLINK": "https://example.org/a"}
        for kind in values:
            self.schema.create_parameter(kind, None, kind, kind)
            if kind in ("ENUM", "MULTI_ENUM"):
                self.schema.add_option(kind, "A", 1)
                self.schema.add_option(kind, "B", 2)
        self.schema.create_parameter("absent", None, "Absent", "TEXT")
        self.schema.create_parameter("empty", None, "Empty", "TEXT")
        self.schema.create_parameter("null", None, "Null", "NUMBER")
        values.update(empty="", null=None)
        pid = self.projects.create_project(name="Round trip", dynamic_attributes=values)
        self.assertEqual(self.projects.get_project_by_id(pid).dynamic_attributes, values)
        self.projects.update_project(pid, "Round trip", "Draft", {"MULTI_ENUM": []})
        self.assertEqual(self.projects.get_project_by_id(pid).dynamic_attributes["MULTI_ENUM"], [])
        for kind, value in [("NUMBER", "12"), ("NUMBER", float("nan")), ("DATE", "2026-99-01"), ("ENUM", "unknown"), ("MULTI_ENUM", ["A", "A"])]:
            with self.subTest(kind=kind, value=value), self.assertRaises(ValueError):
                self.projects.create_project(name="Invalid", dynamic_attributes={kind: value})
        with psycopg.connect(self.setup.operator_url) as connection:
            columns = {row[0] for row in connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='eppm' AND table_name='project'"
            )}
        self.assertNotIn("dynamic_attributes", columns)

    def test_deletion_and_type_change_guards(self):
        self.schema.create_parameter("p", None, "Value", "ENUM")
        option = self.schema.add_option("p", "A", 0)
        a = self.types.create_type("A")
        self.types.save_rule(a, "p", has_default=True, default_value="A")
        for operation in [lambda: self.schema.delete_parameter("p"), lambda: self.schema.delete_option(option), lambda: self.schema.update_parameter("p", None, "Value", "NUMBER"), lambda: self.types.delete_type(1)]:
            with self.assertRaises(ValueError):
                operation()
        pid = self.projects.create_project(name="A", project_type_id=a)
        with self.assertRaises(ValueError):
            self.types.delete_type(a)
        self.projects.delete_project(pid)
        self.types.delete_type(a)
        self.assertTrue(self.schema.delete_option(option))
        self.assertTrue(self.schema.delete_parameter("p"))

    def _assert_seed_valid(self) -> None:
        """Validate every actual seeded project against its native template."""
        with psycopg.connect(self.setup.operator_url) as connection:
            values = read_values(connection)
            store = PostgresProjectStore(connection)
            for project_id, type_id in connection.execute('SELECT id,project_type_id FROM eppm.project'):
                prepare_project_values(store.template(type_id), store.choices(), values.get(project_id, {}), creating=False)

    def test_explicit_demo_reentry_preserves_user_template_rules_and_applicability(self) -> None:
        """Explicit operator reentry preserves existing defaults and custom templates."""
        self.maintenance.seed_defaults()
        rows = self.projects.get_planning_catalog(tuple(parameter.param_id for parameter in self.schema.get_all_parameters()))
        self.assertEqual(len(rows), 5)
        self.assertEqual(len({row['project_template'] for row in rows}), 5)
        self._assert_seed_valid()
        self.types.save_rule(1, "PRM_011", True, has_default=True, default_value="User default")
        self.types.set_applicability("PRM_015", True)
        self.types.create_type("User type")
        self.maintenance.seed_defaults()
        self.assertEqual(len(self.types.get_all_types()), 6)
        self.assertTrue(self.types.get_applicability("PRM_015").applies_to_all)
        self.assertEqual(next(item['default_value'] for item in self.types.get_template(1) if item['param_id'] == 'PRM_011'), 'User default')

    def test_zero_project_generation_cannot_reinsert_demo_on_operator_reentry(self) -> None:
        """Zero is a deliberate workload, followed by a valid task-free append."""
        result = self.maintenance.seed_projects(SeedRequest(projects=0, min_tasks=0, max_tasks=0))
        self.assertEqual(result['projects_created'], 0)
        self.maintenance.seed_defaults()
        self.assertEqual(self.projects.get_planning_catalog(()), [])
        self.maintenance.seed_projects(SeedRequest(projects=2, min_tasks=0, max_tasks=0, clean_first=False))
        with psycopg.connect(self.setup.operator_url) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM eppm.project_task').fetchone()[0], 0)
        self.assertEqual(len(self.projects.get_planning_catalog(())), 2)
        self._assert_seed_valid()
