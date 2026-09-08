"""Full seeds and additive repairs must retain the pool scenario contract."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.seed_database import seed_database
from scripts.seed_pool_scenarios import MARKER, seed_pool_scenarios
from src.database.seeder import seed_default_data_if_empty


class PoolScenarioSeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "data" / "test.db")
        Path(self.path).parent.mkdir()

    def test_full_and_default_reseeds_include_hierarchy_and_scenarios(self):
        seed_database(12, 3, 8, self.path)
        self.assert_scenarios()
        seed_default_data_if_empty(self.path, force=True)
        self.assert_scenarios()
        self.assertEqual(len(list(Path(self.path).parent.glob("backups/*.db"))), 1)

    def assert_scenarios(self):
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM resource_pool").fetchone()[0], 127)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM resource_pool_group").fetchone()[0], 52)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            for gid, in conn.execute("SELECT id FROM resource_pool_group WHERE description=?", (MARKER,)):
                self.assertTrue(1 <= conn.execute("SELECT COUNT(*) FROM resource_pool_group_member WHERE group_id=? AND pool_id IS NOT NULL", (gid,)).fetchone()[0] <= 5)
            for gid, in conn.execute("SELECT id FROM resource_pool_group WHERE description!=?", (MARKER,)):
                self.assertTrue(3 <= conn.execute("SELECT COUNT(*) FROM resource_pool_group_member m JOIN resource_pool_group g ON g.id=m.child_group_id WHERE m.group_id=? AND g.description=?", (gid, MARKER)).fetchone()[0] <= 10)
            mappings = conn.execute("SELECT p.id,COUNT(m.target_id) FROM resource_pool p JOIN resource_pool_mapping m ON m.pool_id=p.id WHERE p.name LIKE 'Service C /%' AND m.target_type='employee' GROUP BY p.id").fetchall()
            self.assertEqual(len(mappings), 24)
            self.assertTrue(all(3 <= count <= 5 for _, count in mappings))
            # Every generated pool has both project-level and task-level demand.
            for pid, in conn.execute("SELECT id FROM resource_pool WHERE description=?", (MARKER,)):
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM resource_pool_assignment WHERE pool_id=?", (pid,)).fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM employee_calendar_exception WHERE occupation_percentage=0 AND reason LIKE ?", (MARKER + '%',)).fetchone()[0], 1)

    def test_additive_repair_preserves_projects_and_is_idempotent(self):
        # Emulate the old full seeder that only created three pools.
        with patch("scripts.seed_pool_scenarios.seed_pool_scenarios", return_value={"new_pools": 0, "new_groups": 0}):
            seed_database(12, 3, 8, self.path)
        with sqlite3.connect(self.path) as conn:
            before = {table: conn.execute("SELECT * FROM " + table).fetchall()
                      for table in ("project", "project_task", "task_dependencies", "project_property_value")}
        report = seed_pool_scenarios(self.path, year=2026)
        self.assertTrue(report["applied"])
        self.assert_scenarios()
        with sqlite3.connect(self.path) as conn:
            for table, rows in before.items():
                self.assertEqual(conn.execute("SELECT * FROM " + table).fetchall(), rows)
        self.assertTrue(seed_pool_scenarios(self.path)["already_seeded"])
        self.assertEqual(len(list(Path(self.path).parent.glob("backups/*.db"))), 1)

    def test_task_free_seed_does_not_invent_tasks(self):
        seed_database(2, 0, 0, self.path)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM project_task").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM resource_pool").fetchone()[0], 127)
