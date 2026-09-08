"""Full seeds and additive repairs must retain the pool scenario contract."""

from contextlib import closing

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
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM resource_pool").fetchone()[0], 103)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM resource_pool_group").fetchone()[0], 31)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            units = conn.execute("SELECT id FROM resource_pool_group WHERE description=?", (MARKER,)).fetchall()
            self.assertEqual(len(units), 25)
            for gid, in units:
                pools = conn.execute("SELECT p.id,p.name,p.capacity_fte FROM resource_pool p JOIN resource_pool_group_member m ON m.pool_id=p.id WHERE m.group_id=?", (gid,)).fetchall()
                self.assertEqual(len(pools), 4)
                for pid, name, theoretical in pools:
                    nominal, count = conn.execute("SELECT COALESCE(SUM(e.occupation_percentage*m.allocation_pct/10000),0),COUNT(*) FROM resource_pool_mapping m JOIN employee e ON m.target_type='employee' AND e.employee_id=m.target_id WHERE m.pool_id=?", (pid,)).fetchone()
                    if name.endswith('/ Unallocated'):
                        self.assertEqual(count, 0)
                        self.assertGreater(theoretical, 0)
                    elif name.endswith('/ Overassigned'):
                        self.assertGreater(nominal, theoretical)
                    elif name.endswith('/ Underassigned'):
                        self.assertLess(nominal, theoretical)
                        self.assertGreater(nominal, 0)
                    else:
                        self.assertTrue(name.endswith('/ Fully assigned'))
                        self.assertAlmostEqual(nominal, theoretical)
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM resource_pool_assignment WHERE pool_id=?", (pid,)).fetchone()[0], 2)
            for gid, in conn.execute("SELECT id FROM resource_pool_group WHERE name LIKE 'Service %' AND description!=?", (MARKER,)):
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM resource_pool_group_member WHERE group_id=? AND child_group_id IS NOT NULL", (gid,)).fetchone()[0], 5)

    def test_additive_repair_preserves_projects_and_is_idempotent(self):
        # Emulate the old full seeder that only created three pools.
        with patch("scripts.seed_pool_scenarios.seed_pool_scenarios", return_value={"new_pools": 0, "new_groups": 0}):
            seed_database(12, 3, 8, self.path)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            before = {table: conn.execute("SELECT * FROM " + table).fetchall()
                      for table in ("project", "project_task", "task_dependencies", "project_property_value")}
        report = seed_pool_scenarios(self.path, year=2026)
        self.assertTrue(report["applied"])
        self.assert_scenarios()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            for table, rows in before.items():
                self.assertEqual(conn.execute("SELECT * FROM " + table).fetchall(), rows)
        self.assertTrue(seed_pool_scenarios(self.path)["already_seeded"])
        self.assertEqual(len(list(Path(self.path).parent.glob("backups/*.db"))), 1)

    def test_task_free_seed_does_not_invent_tasks(self):
        seed_database(2, 0, 0, self.path)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM project_task").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM resource_pool").fetchone()[0], 103)
