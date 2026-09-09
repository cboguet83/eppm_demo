"""Cache correctness: daily exceptions, targeted invalidation and durable reads."""

from app.main import create_pool_capacity_service

from contextlib import closing

import sqlite3
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from app.infrastructure.database.schema_init import init_db
from app.main import create_resource_pool_service
from app.main import capacity_cache_state


class PoolCapacityCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "test.db")
        init_db(self.path)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO project(id,name) VALUES(1,'Project')")
            conn.execute(
                "INSERT INTO project_task(id,project_id,task_name,start_date,end_date) "
                "VALUES(1,1,'Task','2026-01-01','2026-12-31')"
            )
            conn.execute(
                "INSERT INTO employee(employee_id,firstname,lastname,email,employee_code) "
                "VALUES(1,'Test','Employee','test@example.invalid','TEST')"
            )
            conn.executemany(
                "INSERT INTO resource_pool(id,name,capacity_fte) VALUES(?,?,?)",
                [(1, "Employee pool", 2), (2, "Fallback pool", 3)],
            )
            conn.execute(
                "INSERT INTO resource_pool_mapping(pool_id,target_type,target_id) VALUES(1,'employee',1)"
            )
            conn.execute(
                "INSERT INTO resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) VALUES(1,1,1,0.5)"
            )
        capacity_cache_state().entries.clear()

    def test_persisted_details_equal_uncached_service_and_warm_reads_do_not_compute(self):
        expected = [
            asdict(create_pool_capacity_service(self.path).calculate_many([pid])[0])
            for pid in (1, 2)
        ]
        actual = create_pool_capacity_service(self.path).get_details(
            [pool.id for pool in create_resource_pool_service(self.path).get_all_pools()]
        )
        self.assertEqual([asdict(d) for d in actual], expected)
        capacity_cache_state().entries.clear()  # Simulate restarting the app: use persisted JSON.
        with patch(
            "app.application.services.pool_capacity.PoolCapacityService.calculate_many",
            side_effect=AssertionError("recomputed"),
        ):
            self.assertEqual(
                [
                    asdict(d)
                    for d in create_pool_capacity_service(self.path).get_details(
                        [
                            pool.id
                            for pool in create_resource_pool_service(self.path).get_all_pools()
                        ]
                    )
                ],
                expected,
            )
            self.assertEqual(len(create_pool_capacity_service(self.path).get_summaries()), 2)

    def test_single_day_zero_exception_invalidates_only_affected_pool(self):
        create_pool_capacity_service(self.path).get_summaries()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                "INSERT INTO employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage) "
                "VALUES(1,'2026-06-15','2026-06-15',0)"
            )
            self.assertEqual(
                conn.execute("SELECT pool_id FROM pool_capacity_cache").fetchall(), [(2,)]
            )
        detail = create_pool_capacity_service(self.path).get_details([1])[0]
        self.assertTrue(detail.is_overassigned)
        self.assertEqual([d.date for d in detail.daily_overassignments], ["2026-06-15"])
        self.assertEqual(detail.daily_assigned_capacity["2026-06-15"], 0)

    def test_task_dates_mapping_and_capacity_changes_refresh_results(self):
        create_pool_capacity_service(self.path).get_summaries()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE project_task SET end_date='2026-01-02' WHERE id=1")
        detail = create_pool_capacity_service(self.path).get_details([1])[0]
        self.assertEqual(len(detail.daily_usage), 2)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE resource_pool_mapping SET allocation_pct=25 WHERE pool_id=1")
        self.assertTrue(
            create_pool_capacity_service(self.path).get_details([1])[0].is_overassigned
        )
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("DELETE FROM resource_pool_mapping WHERE pool_id=1")
            conn.execute("UPDATE resource_pool SET capacity_fte=0.1 WHERE id=1")
        detail = create_pool_capacity_service(self.path).get_details([1])[0]
        self.assertFalse(detail.has_assigned_resources)
        self.assertEqual(detail.effective_capacity_fte, 0.1)
        self.assertTrue(detail.is_overassigned)

    def test_assignment_retarget_invalidates_old_and_new_pool(self):
        create_pool_capacity_service(self.path).get_summaries()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE resource_pool_assignment SET pool_id=2 WHERE pool_id=1")
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM pool_capacity_cache").fetchone()[0], 0
            )
        results = {
            d.pool_id: d
            for d in create_pool_capacity_service(self.path).get_details(
                [pool.id for pool in create_resource_pool_service(self.path).get_all_pools()]
            )
        }
        self.assertEqual(results[1].daily_usage, {})
        self.assertEqual(results[2].peak_assigned_fte, 0.5)

    def test_retired_cache_format_is_recomputed_without_decoding_old_resource_fields(self):
        """Version-one derived data cannot require a removed Python model alias."""
        import json

        service = create_pool_capacity_service(self.path)
        expected = [asdict(detail) for detail in service.get_details([1, 2])]
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "UPDATE pool_capacity_cache SET version=1, detail=?",
                (json.dumps({"contributing_functions": "retired format"}),),
            )
        capacity_cache_state().entries.clear()

        actual = service.get_details([1, 2])

        self.assertEqual([asdict(detail) for detail in actual], expected)
        with closing(sqlite3.connect(self.path)) as connection:
            for version, payload in connection.execute(
                "SELECT version, detail FROM pool_capacity_cache"
            ):
                self.assertEqual(version, 2)
                self.assertIn("contributing_resources", json.loads(payload))
                self.assertNotIn("contributing_functions", json.loads(payload))
