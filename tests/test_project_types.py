"""Behavioral coverage for templates, relational storage, and safe migration."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.flush_database import flush_database
from scripts.seed_database import seed_database
from src.database.connection import get_db
from src.database.property_store import effective_template, prepare_values, read_values
from src.database.schema_init import init_db
from src.database.seeder import seed_default_data_if_empty
from src.repositories.project_repo import ProjectRepository
from src.repositories.project_type_repo import ProjectTypeRepository
from src.repositories.schema_repo import SchemaRepository
from src.services.portfolio_service import PortfolioService


class ProjectTypesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "test.db")
        init_db(self.path)
        self.types = ProjectTypeRepository(self.path)
        self.schema = SchemaRepository(self.path)
        self.projects = ProjectRepository(self.path)

    def test_all_future_types_and_selected_membership(self):
        a = self.types.create_type("A")
        self.schema.create_parameter("global", None, "Shared", "TEXT")
        self.schema.create_parameter("local", None, "Local", "TEXT", applies_to_all=False, project_type_ids=[a])
        b = self.types.create_type("B")
        self.assertEqual(set(self.types.get_template(a).param_id), {"global", "local"})
        self.assertEqual(set(self.types.get_template(b).param_id), {"global"})
        with self.assertRaises(ValueError):
            self.schema.create_parameter("invalid", None, "Bad", "TEXT", applies_to_all=False)
        self.assertNotIn("invalid", set(self.schema.get_all_parameters().param_id))
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
        self.assertEqual(len(self.projects.get_all_projects()), 2)

    def test_defaults_only_creation_preserve_clear_and_edit(self):
        a = self.types.create_type("A")
        self.schema.create_parameter("p", None, "Value", "TEXT")
        self.types.save_rule(a, "p", has_default=True, default_value="Initial")
        pid = self.projects.create_project(name="Defaulted", project_type_id=a)
        self.assertEqual(self.projects.get_project_by_id(pid).dynamic_attributes, {"p": "Initial"})
        clear = self.projects.create_project(name="Cleared", project_type_id=a, dynamic_attributes={"p": ""})
        self.assertEqual(self.projects.get_project_by_id(clear).dynamic_attributes, {"p": ""})
        self.types.save_rule(a, "p", has_default=True, default_value="Changed")
        self.projects.update_project(pid, "Edited", "Draft", 0, 0, {})
        self.assertEqual(self.projects.get_project_by_id(pid).dynamic_attributes, {"p": "Initial"})
        other = self.projects.create_project(name="Other")
        self.projects.update_project(other, "Switched", "Draft", 0, 0, {}, project_type_id=a)
        self.assertEqual(self.projects.get_project_by_id(other).dynamic_attributes, {})

    def test_inactive_values_retained_hidden_and_restored(self):
        a = self.types.create_type("A")
        self.schema.create_parameter("p", None, "Secret detail", "TEXT", mandatory=True, applies_to_all=False, project_type_ids=[a])
        pid = self.projects.create_project(name="Project", project_type_id=a, dynamic_attributes={"p": "Keep me"})
        self.projects.update_project(pid, "Project", "Draft", 0, 0, {}, project_type_id=1)
        self.assertEqual(self.projects.get_project_by_id(pid).dynamic_attributes, {"p": "Keep me"})
        rows = self.projects.get_all_projects()
        self.assertEqual(rows.iloc[0].dynamic_attributes, {})
        flattened = PortfolioService.flatten_dynamic_attributes(rows, self.schema.get_all_parameters())
        self.assertIsNone(flattened.iloc[0]["p"])
        with self.assertRaises(ValueError):
            self.projects.update_project(pid, "Should roll back", "Draft", 0, 0, {"p": "No"})
        self.assertEqual(self.projects.get_project_by_id(pid).name, "Project")
        self.projects.update_project(pid, "Project", "Draft", 0, 0, {}, project_type_id=a)
        self.assertEqual(self.projects.get_all_projects().iloc[0].dynamic_attributes, {"p": "Keep me"})
        self.types.set_applicability("p", False, [1])
        self.assertEqual(self.projects.get_all_projects().iloc[0].dynamic_attributes, {})

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
        self.projects.update_project(pid, "Round trip", "Draft", 0, 0, {"MULTI_ENUM": []})
        self.assertEqual(self.projects.get_project_by_id(pid).dynamic_attributes["MULTI_ENUM"], [])
        for kind, value in [("NUMBER", "12"), ("NUMBER", float("nan")), ("DATE", "2026-99-01"), ("ENUM", "unknown"), ("MULTI_ENUM", ["A", "A"])]:
            with self.subTest(kind=kind, value=value), self.assertRaises(ValueError):
                self.projects.create_project(name="Invalid", dynamic_attributes={kind: value})
        with get_db(self.path) as conn:
            self.assertNotIn("dynamic_attributes", {r[1] for r in conn.execute("PRAGMA table_info(project)")})
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

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

    def assert_seed_valid(self):
        with get_db(self.path) as conn:
            values = read_values(conn)
            for pid, type_id in conn.execute("SELECT id,project_type_id FROM project"):
                prepare_values(conn, type_id, values.get(pid, {}), creating=False)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_demo_catalog_and_ordinary_startup_preservation(self):
        seed_default_data_if_empty(self.path)
        self.assertEqual(len(self.projects.get_all_projects()), 5)
        self.assertEqual(self.projects.get_all_projects().project_type.nunique(), 5)
        self.assert_seed_valid()
        self.types.save_rule(1, "PRM_011", True, has_default=True, default_value="User default")
        self.types.set_applicability("PRM_015", True)
        self.types.create_type("User type")
        seed_default_data_if_empty(self.path)
        self.assertEqual(len(self.types.get_all_types()), 6)
        self.assertTrue(self.types.get_applicability("PRM_015")[0])
        self.assertEqual(self.types.get_template(1).set_index("param_id").loc["PRM_011", "default_value"], "User default")

    def test_bulk_append_counts_reproducibility_and_flush(self):
        first = seed_database(7, 2, 4, self.path, random_seed=17)
        snapshot = self.projects.get_all_projects().to_dict("records")
        self.assertEqual(first["projects_created"], 7)
        self.assertGreater(first["property_values_created"], 0)
        self.assert_seed_valid()
        seed_database(3, 1, 3, self.path, clean_first=False, random_seed=18)
        self.assertEqual(self.projects.get_all_projects().iloc[:7].to_dict("records"), snapshot)
        self.assertEqual(len(self.projects.get_all_projects()), 10)
        self.assert_seed_valid()
        seed_database(7, 2, 4, self.path, random_seed=17)
        self.assertEqual(self.projects.get_all_projects().to_dict("records"), snapshot)
        flush_database(self.path)
        with get_db(self.path) as conn:
            self.assertEqual(read_values(conn), {})
            self.assertTrue(read_values(conn, defaults=True))
        self.assertEqual(len(self.types.get_all_types()), 5)
        flush_database(self.path, flush_all=True)
        seed_default_data_if_empty(self.path)
        self.assert_seed_valid()

    def test_zero_projects_and_no_bootstrap_reinsertion(self):
        summary = seed_database(0, 0, 0, self.path)
        self.assertEqual(summary["projects_created"], 0)
        seed_default_data_if_empty(self.path)
        self.assertTrue(self.projects.get_all_projects().empty)
        seed_database(2, 0, 0, self.path, clean_first=False)
        with get_db(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM project_task").fetchone()[0], 0)

    def test_bulk_respects_large_minimum_and_deleted_high_ids(self):
        seed_database(2, 20, 20, self.path)
        with get_db(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM project_task GROUP BY project_id").fetchall(), [(20,), (20,)])
        self.projects.delete_project(2)
        seed_database(2, 2, 4, self.path, clean_first=False)
        self.assertEqual(self.projects.get_all_projects().id.tolist(), [1, 3, 4])
        self.assert_seed_valid()

    def test_custom_catalog_append_and_reference_only_initialization(self):
        a = self.types.create_type("User type")
        self.schema.create_parameter("p", None, "Choice", "ENUM", mandatory=True)
        self.schema.add_option("p", "User choice", 1)
        seed_database(3, 0, 0, self.path, clean_first=False)
        self.assertEqual(len(self.types.get_all_types()), 2)
        self.assert_seed_valid()
        with get_db(self.path) as conn:
            self.assertEqual(conn.execute("SELECT DISTINCT text_value FROM project_property_value").fetchall(), [("User choice",)])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM employee").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM resource_pool").fetchone()[0], 0)


class ProjectTypeMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "legacy.db")

    def legacy(self, raw, *, ambiguous=False):
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE schema_groups(id INTEGER PRIMARY KEY,group_name TEXT,display_order INTEGER)")
            conn.execute("CREATE TABLE schema_parameters(param_id TEXT PRIMARY KEY,group_id INTEGER,param_name TEXT,param_type TEXT,mandatory INTEGER,alias TEXT)")
            conn.execute("INSERT INTO schema_parameters VALUES ('p',NULL,'Name','TEXT',1,'Alias')")
            if ambiguous:
                conn.execute("INSERT INTO schema_parameters VALUES ('q',NULL,'Name','TEXT',0,'Other')")
            conn.execute("CREATE TABLE project(id INTEGER PRIMARY KEY,name TEXT,status TEXT,planned_budget REAL,actual_budget REAL,dynamic_attributes TEXT)")
            conn.execute("INSERT INTO project VALUES (10,'Legacy','Draft',10,0,?)", (raw,))

    def test_migration_preserves_values_backup_and_idempotency(self):
        self.legacy(json.dumps({"Alias": "Preserved"}))
        init_db(self.path)
        project = ProjectRepository(self.path).get_project_by_id(10)
        self.assertEqual(project.project_type_id, 1)
        self.assertEqual(project.dynamic_attributes, {"p": "Preserved"})
        backup = Path(self.path + ".before-project-types.bak")
        self.assertTrue(backup.exists())
        with sqlite3.connect(backup) as conn:
            self.assertEqual(json.loads(conn.execute("SELECT dynamic_attributes FROM project").fetchone()[0]), {"Alias": "Preserved"})
        init_db(self.path)
        seed_default_data_if_empty(self.path)
        with get_db(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM project_property_value").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT mandatory,applies_to_all FROM schema_parameters").fetchone(), (1, 1))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM project_type").fetchone()[0], 1)

    def test_bad_legacy_data_rolls_back_every_schema_change(self):
        for raw, ambiguous in [('broken', False), ('[]', False), ('{"unknown":1}', False), ('{"p":1}', False), ('{"p":"a","Name":"b"}', False), ('{"p":"a","p":"a"}', False), ('{"Name":"a"}', True)]:
            with self.subTest(raw=raw):
                self.path = str(Path(self.directory.name) / f"legacy-{len(list(Path(self.directory.name).glob('*.db')))}.db")
                self.legacy(raw, ambiguous=ambiguous)
                with self.assertRaises(ValueError):
                    init_db(self.path)
                with sqlite3.connect(self.path) as conn:
                    self.assertEqual(conn.execute("SELECT dynamic_attributes FROM project").fetchone()[0], raw)
                    self.assertFalse(conn.execute("SELECT 1 FROM sqlite_master WHERE name='project_type'").fetchone())
                    self.assertNotIn("applies_to_all", {r[1] for r in conn.execute("PRAGMA table_info(schema_parameters)")})

    def test_unrelated_legacy_orphans_are_preserved_and_reported(self):
        self.legacy('{"p":"Keep"}')
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE external_record(id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES project(id))")
            conn.execute("INSERT INTO external_record VALUES (1,999)")
        with self.assertLogs("src.database.project_type_migration", level="WARNING") as logs:
            init_db(self.path)
        self.assertIn("pre-existing", logs.output[0])
        with get_db(self.path) as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [("external_record", 1, "project", 0)])
            self.assertEqual(read_values(conn), {10: {"p": "Keep"}})
