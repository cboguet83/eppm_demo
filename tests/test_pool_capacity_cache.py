"""Cache correctness: daily exceptions, targeted invalidation and durable reads."""

from contextlib import closing

import sqlite3
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from src.database.schema_init import init_db
from src.repositories.resource_pool_repo import ResourcePoolRepository
from src.services.pool_capacity_cache import _MEMORY, load_pool_capacities


class PoolCapacityCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "test.db")
        init_db(self.path)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO project(id,name) VALUES(1,'Project')")
            conn.execute("INSERT INTO project_task(id,project_id,task_name,start_date,end_date) "
                         "VALUES(1,1,'Task','2026-01-01','2026-12-31')")
            conn.execute("INSERT INTO employee(employee_id,firstname,lastname,email,employee_code) "
                         "VALUES(1,'Test','Employee','test@example.invalid','TEST')")
            conn.executemany("INSERT INTO resource_pool(id,name,capacity_fte) VALUES(?,?,?)",
                             [(1, "Employee pool", 2), (2, "Fallback pool", 3)])
            conn.execute("INSERT INTO resource_pool_mapping(pool_id,target_type,target_id) VALUES(1,'employee',1)")
            conn.execute("INSERT INTO resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) VALUES(1,1,1,0.5)")
        _MEMORY.clear()

    def test_persisted_details_equal_uncached_service_and_warm_reads_do_not_compute(self):
        expected = [asdict(ResourcePoolRepository(self.path).get_pool_capacity_detail(pid)) for pid in (1, 2)]
        actual = load_pool_capacities(self.path, details=True)
        self.assertEqual([asdict(d) for d in actual], expected)
        _MEMORY.clear()  # Simulate restarting the app: use persisted JSON.
        with patch("src.services.pool_capacity_cache._batch_calculate", side_effect=AssertionError("recomputed")):
            self.assertEqual([asdict(d) for d in load_pool_capacities(self.path, details=True)], expected)
            self.assertEqual(len(load_pool_capacities(self.path)), 2)

    def test_single_day_zero_exception_invalidates_only_affected_pool(self):
        load_pool_capacities(self.path)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage) "
                         "VALUES(1,'2026-06-15','2026-06-15',0)")
            self.assertEqual(conn.execute("SELECT pool_id FROM pool_capacity_cache").fetchall(), [(2,)])
        detail = load_pool_capacities(self.path, details=True, pool_ids=[1])[0]
        self.assertTrue(detail.is_overassigned)
        self.assertEqual([d.date for d in detail.daily_overassignments], ["2026-06-15"])
        self.assertEqual(detail.daily_assigned_capacity["2026-06-15"], 0)

    def test_task_dates_mapping_and_capacity_changes_refresh_results(self):
        load_pool_capacities(self.path)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE project_task SET end_date='2026-01-02' WHERE id=1")
        detail = load_pool_capacities(self.path, details=True, pool_ids=[1])[0]
        self.assertEqual(len(detail.daily_usage), 2)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE resource_pool_mapping SET allocation_pct=25 WHERE pool_id=1")
        self.assertTrue(load_pool_capacities(self.path, details=True, pool_ids=[1])[0].is_overassigned)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("DELETE FROM resource_pool_mapping WHERE pool_id=1")
            conn.execute("UPDATE resource_pool SET capacity_fte=0.1 WHERE id=1")
        detail = load_pool_capacities(self.path, details=True, pool_ids=[1])[0]
        self.assertFalse(detail.has_assigned_resources)
        self.assertEqual(detail.effective_capacity_fte, 0.1)
        self.assertTrue(detail.is_overassigned)

    def test_assignment_retarget_invalidates_old_and_new_pool(self):
        load_pool_capacities(self.path)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE resource_pool_assignment SET pool_id=2 WHERE pool_id=1")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pool_capacity_cache").fetchone()[0], 0)
        results = {d.pool_id: d for d in load_pool_capacities(self.path, details=True)}
        self.assertEqual(results[1].daily_usage, {})
        self.assertEqual(results[2].peak_assigned_fte, 0.5)
