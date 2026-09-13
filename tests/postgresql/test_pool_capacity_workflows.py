"""Cache correctness: daily exceptions, targeted invalidation and durable reads."""

from app.main import create_pool_capacity_cache, create_pool_capacity_service


import psycopg
from psycopg.types.json import Jsonb
import pytest
from datetime import date
from app.application.services.business_access import BusinessAccess
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access
import unittest
from dataclasses import asdict
from unittest.mock import patch

from app.main import create_resource_pool_service


class PoolCapacityCacheTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def native_setup(self, authorized: AuthorizedFixture, runtime: RuntimeResources, access: BusinessAccess) -> None:
        """Use native services with two independently invalidatable capacity pools."""
        self.setup, self.resources, self.access = authorized.setup, runtime, access
        with psycopg.connect(self.setup.operator_url) as conn, conn.cursor() as cursor:
            conn.execute("UPDATE eppm.project SET name='Project' WHERE id=1")
            conn.execute(
                "INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date) "
                "VALUES(1,1,'Task','2026-01-01','2026-12-31')"
            )
            conn.execute(
                "INSERT INTO eppm.employee(employee_id,firstname,lastname,email,employee_code) "
                "VALUES(1,'Test','Employee','test@example.invalid','TEST')"
            )
            cursor.executemany(
                "INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(%s,%s,%s)",
                [(1, "Employee pool", 2), (2, "Fallback pool", 3)],
            )
            conn.execute(
                "INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id) VALUES(1,'employee',1)"
            )
            conn.execute(
                "INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned) VALUES(1,1,1,0.5)"
            )

    def test_persisted_details_equal_uncached_service_and_warm_reads_do_not_compute(self) -> None:
        expected = [
            asdict(create_pool_capacity_service(self.resources, access=self.access).calculate_many([pid])[0])
            for pid in (1, 2)
        ]
        actual = create_pool_capacity_service(self.resources, access=self.access).get_details(
            [pool.id for pool in create_resource_pool_service(self.resources, access=self.access).get_all_pools()]
        )
        self.assertEqual([asdict(d) for d in actual], expected)
        self.resources = RuntimeResources(self.resources.database, self.resources.key)
        with patch(
            "app.application.services.pool_capacity.PoolCapacityService.calculate_many",
            side_effect=AssertionError("recomputed"),
        ):
            self.assertEqual(
                [
                    asdict(d)
                    for d in create_pool_capacity_service(self.resources, access=self.access).get_details(
                        [
                            pool.id
                            for pool in create_resource_pool_service(self.resources, access=self.access).get_all_pools()
                        ]
                    )
                ],
                expected,
            )
            self.assertEqual(len(create_pool_capacity_service(self.resources, access=self.access).get_summaries()), 2)

    def test_single_day_zero_exception_invalidates_shared_staffing_results(self) -> None:
        """Calendar changes advance the native shared-catalog revision."""
        create_pool_capacity_service(self.resources, access=self.access).get_summaries()
        with psycopg.connect(self.setup.operator_url) as conn:
            conn.execute(
                "INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage) "
                "VALUES(1,'2026-06-15','2026-06-15',0)"
            )
        self.assertEqual(self._valid_cached_pool_ids(), [])
        detail = create_pool_capacity_service(self.resources, access=self.access).get_details([1])[0]
        self.assertTrue(detail.is_overassigned)
        self.assertEqual([d.date for d in detail.daily_overassignments], ["2026-06-15"])
        self.assertEqual(detail.daily_assigned_capacity["2026-06-15"], 0)

    def test_task_dates_mapping_and_capacity_changes_refresh_results(self) -> None:
        create_pool_capacity_service(self.resources, access=self.access).get_summaries()
        with psycopg.connect(self.setup.operator_url) as conn:
            conn.execute("UPDATE eppm.project_task SET end_date='2026-01-02' WHERE id=1")
        detail = create_pool_capacity_service(self.resources, access=self.access).get_details([1])[0]
        self.assertEqual(len(detail.daily_usage), 2)
        with psycopg.connect(self.setup.operator_url) as conn:
            conn.execute("UPDATE eppm.resource_pool_mapping SET allocation_pct=25 WHERE pool_id=1")
        self.assertEqual(self._valid_cached_pool_ids(), [2])
        self.assertTrue(
            create_pool_capacity_service(self.resources, access=self.access).get_details([1])[0].is_overassigned
        )
        with psycopg.connect(self.setup.operator_url) as conn:
            conn.execute("DELETE FROM eppm.resource_pool_mapping WHERE pool_id=1")
            conn.execute("UPDATE eppm.resource_pool SET capacity_fte=0.1 WHERE id=1")
        detail = create_pool_capacity_service(self.resources, access=self.access).get_details([1])[0]
        self.assertFalse(detail.has_assigned_resources)
        self.assertEqual(detail.effective_capacity_fte, 0.1)
        self.assertTrue(detail.is_overassigned)

    def test_assignment_retarget_invalidates_old_and_new_pool(self) -> None:
        create_pool_capacity_service(self.resources, access=self.access).get_summaries()
        with psycopg.connect(self.setup.operator_url) as conn:
            conn.execute("UPDATE eppm.resource_pool_assignment SET pool_id=2 WHERE pool_id=1")
        self.assertEqual(self._valid_cached_pool_ids(), [])
        results = {
            d.pool_id: d
            for d in create_pool_capacity_service(self.resources, access=self.access).get_details(
                [pool.id for pool in create_resource_pool_service(self.resources, access=self.access).get_all_pools()]
            )
        }
        self.assertEqual(results[1].daily_usage, {})
        self.assertEqual(results[2].peak_assigned_fte, 0.5)

    def _valid_cached_pool_ids(self) -> list[int]:
        """Read the current revision contract instead of private stale physical rows."""
        cache = create_pool_capacity_cache(self.resources, access=self.access).cache
        return [row[0] for row in cache.read('capacity', [1, 2], date.today(), True, []) if row[3]]

    def test_incompatible_cache_format_is_recomputed_before_decoding_its_payload(self) -> None:
        """Only the current native format may be decoded into capacity records."""
        service = create_pool_capacity_service(self.resources, access=self.access)
        expected = [asdict(detail) for detail in service.get_details([1, 2])]
        with psycopg.connect(self.setup.operator_url) as connection:
            connection.execute(
                "UPDATE eppm.pool_capacity_cache SET format_version=2, detail=%s",
                (Jsonb({"contributing_functions": "incompatible format"}),),
            )
        self.resources = RuntimeResources(self.resources.database, self.resources.key)
        service = create_pool_capacity_service(self.resources, access=self.access)
        actual = service.get_details([1, 2])
        self.assertEqual([asdict(detail) for detail in actual], expected)
        with psycopg.connect(self.setup.operator_url) as connection:
            rows = connection.execute("SELECT format_version, detail FROM eppm.pool_capacity_cache").fetchall()
        self.assertEqual(len(rows), 2)
        for version, payload in rows:
            self.assertEqual(version, 1)
            self.assertIn("contributing_resources", payload)
            self.assertNotIn("contributing_functions", payload)
