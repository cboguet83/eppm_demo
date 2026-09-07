"""Unit tests for Resource Pools, partial mappings, de-duplication, and daily overassignment detection."""

import os
import tempfile
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from src.database.schema_init import init_db
from src.models.organization import Employee, EmployeeCalendarException, OrgFunction, Team
from src.models.project import Project
from src.models.resource_pool import PoolAssignment, PoolMapping, ResourcePool
from src.i18n import set_current_locale, t
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.resource_pool_repo import ResourcePoolRepository
from src.services.resource_pool_service import ResourcePoolService


class TestResourcePools(unittest.TestCase):
    """Test suite covering ResourcePoolRepository and ResourcePoolService."""

    def setUp(self) -> None:
        """Sets up a temporary SQLite database for test isolation."""
        set_current_locale("en")
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()
        init_db(self.db_path)

        self.pool_repo = ResourcePoolRepository(self.db_path)
        self.org_repo = OrganizationRepository(self.db_path)
        self.project_repo = ProjectRepository(self.db_path)
        self.milestone_repo = MilestoneRepository(self.db_path)

    def tearDown(self) -> None:
        """Cleans up the temporary SQLite database."""
        if os.path.exists(self.db_path):
            try:
                os.unlink(self.db_path)
            except PermissionError:
                pass

    def test_pool_crud(self) -> None:
        """Verify Create, Read, Update, Delete for ResourcePool."""
        # 1. Create
        p_id = self.pool_repo.create_pool(
            ResourcePool(name="Frontend Pool", description="Web & Mobile UI Squad")
        )
        self.assertGreater(p_id, 0)

        # 2. Read
        p_obj = self.pool_repo.get_pool_by_id(p_id)
        self.assertIsNotNone(p_obj)
        self.assertEqual(p_obj.name, "Frontend Pool")
        self.assertEqual(p_obj.description, "Web & Mobile UI Squad")

        # 3. Update
        updated = self.pool_repo.update_pool(
            ResourcePool(id=p_id, name="Frontend & Mobile Pool", description="Updated Squad")
        )
        self.assertTrue(updated)
        p_mod = self.pool_repo.get_pool_by_id(p_id)
        self.assertEqual(p_mod.name, "Frontend & Mobile Pool")

        # 4. List
        df_pools = self.pool_repo.get_all_pools()
        self.assertEqual(len(df_pools), 1)

        # 5. Delete
        self.assertTrue(self.pool_repo.delete_pool(p_id))
        self.assertIsNone(self.pool_repo.get_pool_by_id(p_id))

    def test_pool_mapping_crud_and_allocations(self) -> None:
        """Verify adding and updating team and function mappings with partial allocations (0-100%)."""
        p_id = self.pool_repo.create_pool(ResourcePool(name="Backend Pool"))
        fn_id = self.org_repo.create_function(OrgFunction(name="Senior Python Dev", hierarchy_level=3))
        tm_id = self.org_repo.create_team(Team(team_name="Cloud Platform Squad"))

        # Map Function at 75%
        m1_id = self.pool_repo.create_mapping(
            PoolMapping(pool_id=p_id, target_type="function", target_id=fn_id, allocation_pct=75.0)
        )
        self.assertGreater(m1_id, 0)

        # Map Team at 50%
        m2_id = self.pool_repo.create_mapping(
            PoolMapping(pool_id=p_id, target_type="team", target_id=tm_id, allocation_pct=50.0)
        )
        self.assertGreater(m2_id, 0)

        df_maps = self.pool_repo.get_mappings_by_pool(p_id)
        self.assertEqual(len(df_maps), 2)

        # Update mapping allocation
        self.pool_repo.update_mapping(m1_id, 80.0)
        df_maps_after = self.pool_repo.get_mappings_by_pool(p_id)
        fn_row = df_maps_after[df_maps_after["target_type"] == "function"].iloc[0]
        self.assertEqual(fn_row["allocation_pct"], 80.0)

        # Delete mapping
        self.assertTrue(self.pool_repo.delete_mapping(m1_id))
        self.assertEqual(len(self.pool_repo.get_mappings_by_pool(p_id)), 1)

    def test_pool_capacity_deduplication(self) -> None:
        """Verify that a function mapped directly AND through an assigned team is considered strictly once."""
        # 1. Create Functions: F1 (100% FTE = 1.0), F2 (100% FTE = 1.0)
        f1_id = self.org_repo.create_function(OrgFunction(name="Lead Architect", hierarchy_level=2, fte_percentage=100))
        f2_id = self.org_repo.create_function(OrgFunction(name="Security Engineer", hierarchy_level=3, fte_percentage=100))

        # 2. Create Team and assign both F1 and F2 to Team
        t_id = self.org_repo.create_team(Team(team_name="Infrastructure Team", manager_function_id=f1_id))
        self.pool_repo.set_team_functions(t_id, [f1_id, f2_id])

        # 3. Create Pool
        p_id = self.pool_repo.create_pool(ResourcePool(name="Hybrid Pool"))

        # Map Team at 100%
        self.pool_repo.create_mapping(
            PoolMapping(pool_id=p_id, target_type="team", target_id=t_id, allocation_pct=100.0)
        )
        # Directly map F1 at 50%
        self.pool_repo.create_mapping(
            PoolMapping(pool_id=p_id, target_type="function", target_id=f1_id, allocation_pct=50.0)
        )

        # 4. Calculate capacity
        cap_detail = ResourcePoolService.calculate_pool_capacity(p_id, self.org_repo, self.pool_repo)

        # F1 must be counted strictly ONCE!
        # If counted twice, total capacity would be: 1.0 (team) + 1.0 (team) + 0.5 (direct) = 2.5 FTE.
        # With deduplication: F1 is 0.5 FTE (direct override), F2 is 1.0 FTE (team). Total = 1.5 FTE!
        self.assertEqual(len(cap_detail.contributing_functions), 2)
        self.assertEqual(cap_detail.total_capacity_fte, 1.5)

        # Check deduplication flag
        f1_contrib = next(c for c in cap_detail.contributing_functions if c.function_id == f1_id)
        f2_contrib = next(c for c in cap_detail.contributing_functions if c.function_id == f2_id)

        self.assertTrue(f1_contrib.is_deduplicated)
        self.assertEqual(f1_contrib.effective_allocation_pct, 50.0)
        self.assertEqual(f1_contrib.effective_fte, 0.5)

        self.assertFalse(f2_contrib.is_deduplicated)
        self.assertEqual(f2_contrib.effective_allocation_pct, 100.0)
        self.assertEqual(f2_contrib.effective_fte, 1.0)

    def test_defined_and_employee_assigned_capacity_are_separate_and_deduplicated(self) -> None:
        """An employee reached directly and through several teams contributes only once."""
        function_id = self.org_repo.create_function(
            OrgFunction(name="Delivery Engineer", hierarchy_level=3, fte_percentage=100)
        )
        employee_id = self.org_repo.create_employee(
            Employee(
                firstname="Ada",
                lastname="Lovelace",
                email="ada@example.test",
                employee_code="EMP-ADA",
                function_id=function_id,
                occupation_percentage=80.0,
            )
        )
        team_a = self.org_repo.create_team(Team(team_name="Team A"))
        team_b = self.org_repo.create_team(Team(team_name="Team B"))
        self.pool_repo.set_team_functions(team_a, [function_id])
        self.pool_repo.set_team_functions(team_b, [function_id])

        pool_id = self.pool_repo.create_pool(
            ResourcePool(name="Defined Pool", capacity_fte=2.5)
        )
        self.pool_repo.create_mapping(
            PoolMapping(pool_id=pool_id, target_type="team", target_id=team_a, allocation_pct=100.0)
        )
        self.pool_repo.create_mapping(
            PoolMapping(pool_id=pool_id, target_type="team", target_id=team_b, allocation_pct=50.0)
        )
        self.pool_repo.create_mapping(
            PoolMapping(
                pool_id=pool_id,
                target_type="employee",
                target_id=employee_id,
                allocation_pct=75.0,
            )
        )
        self.org_repo.create_employee_calendar_exception(
            EmployeeCalendarException(
                employee_id=employee_id,
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 3),
                occupation_percentage=0.0,
                reason="Leave",
            )
        )

        detail = ResourcePoolService.calculate_pool_capacity(
            pool_id, self.org_repo, self.pool_repo
        )

        self.assertEqual(detail.defined_capacity_fte, 2.5)
        self.assertEqual(detail.total_capacity_fte, 2.5)
        self.assertEqual(detail.assigned_capacity_fte, 0.6)
        self.assertEqual(len(detail.contributing_resources), 1)
        contribution = detail.contributing_resources[0]
        self.assertEqual(contribution.resource_type, "employee")
        self.assertEqual(contribution.employee_id, employee_id)
        self.assertEqual(contribution.resource_name, "Ada Lovelace")
        self.assertTrue(contribution.is_deduplicated)
        self.assertEqual(contribution.effective_allocation_pct, 75.0)
        self.assertEqual(detail.daily_assigned_capacity["2026-10-01"], 0.0)
        self.assertEqual(detail.daily_assigned_capacity["2026-10-03"], 0.0)
        self.assertNotIn("2026-09-30", detail.daily_assigned_capacity)

    def test_daily_overassignment_detection(self) -> None:
        """Verify that overassignment is calculated on a daily basis and detects overlapping peak FTE."""
        # 1. Create Function (2.0 FTE capacity)
        f1_id = self.org_repo.create_function(OrgFunction(name="Dev 1", hierarchy_level=3, fte_percentage=100))
        f2_id = self.org_repo.create_function(OrgFunction(name="Dev 2", hierarchy_level=3, fte_percentage=100))

        # 2. Pool with capacity 2.0 FTE
        p_id = self.pool_repo.create_pool(ResourcePool(name="Dev Squad Pool"))
        self.pool_repo.create_mapping(PoolMapping(pool_id=p_id, target_type="function", target_id=f1_id, allocation_pct=100.0))
        self.pool_repo.create_mapping(PoolMapping(pool_id=p_id, target_type="function", target_id=f2_id, allocation_pct=100.0))

        # 3. Create Project and Tasks
        self.project_repo.create_project(
            project_id=10,
            name="Alpha Project",
            status="In Progress",
            planned_budget=100000.0,
            actual_budget=20000.0,
            dynamic_attributes={},
        )
        t1_id = self.milestone_repo.create_milestone(
            project_id=10,
            task_name="Task 1",
            phase="Phase 1",
            start_date="2026-03-01",
            end_date="2026-03-15",
            progress_pct=0,
        )
        t2_id = self.milestone_repo.create_milestone(
            project_id=10,
            task_name="Task 2",
            phase="Phase 1",
            start_date="2026-03-10",
            end_date="2026-03-25",
            progress_pct=0,
        )

        # Assignment 1: Task 1 requires 1.5 FTE (2026-03-01 to 2026-03-15)
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=10,
                task_id=t1_id,
                fte_assigned=1.5,
                notes="Task 1 allocation",
            )
        )

        # First evaluation: Only Assignment 1 -> 1.5 FTE <= 2.0 FTE -> NOT overassigned
        cap_detail_1 = ResourcePoolService.calculate_pool_capacity(
            p_id, self.org_repo, self.pool_repo, self.milestone_repo
        )
        self.assertFalse(cap_detail_1.is_overassigned)
        self.assertEqual(cap_detail_1.peak_assigned_fte, 1.5)
        self.assertEqual(len(cap_detail_1.daily_overassignments), 0)

        # Assignment 2: Task 2 requires 1.0 FTE (2026-03-10 to 2026-03-25)
        # Overlap occurs from 2026-03-10 to 2026-03-15 where total = 1.5 + 1.0 = 2.5 FTE > 2.0 FTE!
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=10,
                task_id=t2_id,
                fte_assigned=1.0,
                notes="Task 2 allocation",
            )
        )

        # Second evaluation: Overassigned on overlapping days!
        cap_detail_2 = ResourcePoolService.calculate_pool_capacity(
            p_id, self.org_repo, self.pool_repo, self.milestone_repo
        )
        self.assertTrue(cap_detail_2.is_overassigned)
        self.assertEqual(cap_detail_2.peak_assigned_fte, 2.5)
        self.assertEqual(cap_detail_2.peak_excess_fte, 0.5)

        # Exactly 6 days of overassignment (2026-03-10 through 2026-03-15 inclusive)
        self.assertEqual(len(cap_detail_2.daily_overassignments), 6)
        self.assertEqual(cap_detail_2.daily_overassignments[0].date, "2026-03-10")
        self.assertEqual(cap_detail_2.daily_overassignments[-1].date, "2026-03-15")
        for over in cap_detail_2.daily_overassignments:
            self.assertEqual(over.capacity_fte, 2.0)
            self.assertEqual(over.assigned_fte, 2.5)
            self.assertEqual(over.excess_fte, 0.5)

        # Check interval formatting
        self.assertIn("2026-03-10 to 2026-03-15 (+0.50 FTE)", cap_detail_2.overassignment_intervals[0])

    def test_custom_date_period_assignment(self) -> None:
        """Verify that an assignment with a specific custom date period is scoped strictly to that period."""
        f_id = self.org_repo.create_function(OrgFunction(name="Specialist", hierarchy_level=3, fte_percentage=100))
        p_id = self.pool_repo.create_pool(ResourcePool(name="Specialist Pool"))
        self.pool_repo.create_mapping(PoolMapping(pool_id=p_id, target_type="function", target_id=f_id, allocation_pct=100.0))

        self.project_repo.create_project(
            project_id=20,
            name="Beta Project",
            status="In Progress",
            planned_budget=50000.0,
            actual_budget=10000.0,
            dynamic_attributes={},
        )
        t_id = self.milestone_repo.create_milestone(
            project_id=20,
            task_name="Long Milestone",
            phase="Phase 1",
            start_date="2026-01-01",
            end_date="2026-12-31",
            progress_pct=0,
        )

        # Assign with custom narrow period (2026-06-01 to 2026-06-15) instead of full year
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=20,
                task_id=t_id,
                fte_assigned=2.0,  # Exceeds 1.0 FTE capacity
                start_date="2026-06-01",
                end_date="2026-06-15",
                notes="Peak sprint",
            )
        )

        cap_detail = ResourcePoolService.calculate_pool_capacity(
            p_id, self.org_repo, self.pool_repo, self.milestone_repo
        )
        self.assertTrue(cap_detail.is_overassigned)
        self.assertEqual(len(cap_detail.daily_overassignments), 15)
        self.assertEqual(cap_detail.daily_overassignments[0].date, "2026-06-01")
        self.assertEqual(cap_detail.daily_overassignments[-1].date, "2026-06-15")

    def test_project_pool_status(self) -> None:
        """Verify calculate_project_pool_status evaluates project-level peak demand and overassignment."""
        f_id = self.org_repo.create_function(OrgFunction(name="Engineer", hierarchy_level=3, fte_percentage=100))
        p_id = self.pool_repo.create_pool(ResourcePool(name="Eng Pool"))
        self.pool_repo.create_mapping(PoolMapping(pool_id=p_id, target_type="function", target_id=f_id, allocation_pct=100.0))

        self.project_repo.create_project(
            project_id=30,
            name="Gamma Project",
            status="In Progress",
            planned_budget=80000.0,
            actual_budget=0.0,
            dynamic_attributes={},
        )

        # Direct project-level assignment of 1.5 FTE (capacity = 1.0 FTE)
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=30,
                task_id=None,
                fte_assigned=1.5,
                start_date="2026-05-01",
                end_date="2026-05-31",
            )
        )

        proj_status = ResourcePoolService.calculate_project_pool_status(
            project_id=30, pool_id=p_id, org_repo=self.org_repo, pool_repo=self.pool_repo, milestone_repo=self.milestone_repo
        )
        self.assertTrue(proj_status["is_overassigned"])
        self.assertEqual(proj_status["project_peak_assigned_fte"], 1.5)
        self.assertEqual(proj_status["excess_fte"], 0.5)

    def test_validation_rules(self) -> None:
        """Verify ResourcePoolService validation constraints."""
        with self.assertRaises(ValueError):
            ResourcePoolService.validate_pool_name("")
        with self.assertRaises(ValueError):
            ResourcePoolService.validate_pool_name("   ")

        with self.assertRaises(ValueError):
            ResourcePoolService.validate_allocation_pct(-5.0)
        with self.assertRaises(ValueError):
            ResourcePoolService.validate_allocation_pct(105.0)

        with self.assertRaises(ValueError):
            ResourcePoolService.validate_fte(-1.0)

    def test_get_task_assignments_map_and_milestone_by_id(self) -> None:
        """Verify get_task_assignments_map and get_milestone_by_id methods."""
        f_id = self.org_repo.create_function(OrgFunction(name="Tester", hierarchy_level=2, fte_percentage=100))
        p_id = self.pool_repo.create_pool(ResourcePool(name="QA Pool"))
        self.pool_repo.create_mapping(PoolMapping(pool_id=p_id, target_type="function", target_id=f_id, allocation_pct=100.0))

        self.project_repo.create_project(
            project_id=40,
            name="Project Gamma",
            status="Draft",
            planned_budget=20000.0,
            actual_budget=0.0,
            dynamic_attributes={},
        )
        t1_id = self.milestone_repo.create_milestone(
            project_id=40,
            task_name="Task A",
            phase="Phase 1",
            start_date="2026-06-01",
            end_date="2026-06-10",
            progress_pct=10,
        )
        t2_id = self.milestone_repo.create_milestone(
            project_id=40,
            task_name="Task B",
            phase="Phase 1",
            start_date="2026-06-11",
            end_date="2026-06-20",
            progress_pct=20,
        )

        # Test get_milestone_by_id
        m1 = self.milestone_repo.get_milestone_by_id(t1_id)
        self.assertIsNotNone(m1)
        self.assertEqual(m1["task_name"], "Task A")
        self.assertEqual(m1["start_date"], "2026-06-01")
        self.assertEqual(m1["end_date"], "2026-06-10")

        m_nonexistent = self.milestone_repo.get_milestone_by_id(999999)
        self.assertIsNone(m_nonexistent)

        # Test empty map
        self.assertEqual(self.pool_repo.get_task_assignments_map([]), {})
        self.assertEqual(self.pool_repo.get_task_assignments_map([999999]), {})

        # Assign pool to Task A and Task B
        self.pool_repo.create_assignment(
            PoolAssignment(pool_id=p_id, project_id=40, task_id=t1_id, fte_assigned=1.2)
        )
        self.pool_repo.create_assignment(
            PoolAssignment(pool_id=p_id, project_id=40, task_id=t2_id, fte_assigned=0.8)
        )

        task_map = self.pool_repo.get_task_assignments_map([t1_id, t2_id])
        self.assertIn(t1_id, task_map)
        self.assertIn(t2_id, task_map)
        self.assertEqual(task_map[t1_id][0]["fte"], 1.2)
        self.assertEqual(task_map[t1_id][0]["pool_name"], "QA Pool")
        self.assertEqual(task_map[t2_id][0]["fte"], 0.8)

    def test_portfolio_pools_summary(self) -> None:
        """Verify get_portfolio_pools_summary returns List[PoolCapacityDetail] correctly."""
        f_id = self.org_repo.create_function(OrgFunction(name="QA Engineer", hierarchy_level=2, fte_percentage=100))
        p_id = self.pool_repo.create_pool(ResourcePool(name="QA Pool"))
        self.pool_repo.create_mapping(PoolMapping(pool_id=p_id, target_type="function", target_id=f_id, allocation_pct=100.0))

        summary = ResourcePoolService.get_portfolio_pools_summary(
            self.org_repo, self.pool_repo, self.milestone_repo
        )
        self.assertIsInstance(summary, list)
        self.assertGreaterEqual(len(summary), 1)
        self.assertEqual(summary[0].pool_name, "QA Pool")
        self.assertGreaterEqual(summary[0].total_capacity_fte, 1.0)

    def test_pool_repo_capacity_detail_and_aliases(self) -> None:
        """Verify get_all_resource_pools, get_pool_capacity_detail, and property aliases."""
        f_id = self.org_repo.create_function(
            OrgFunction(name="DevOps Lead", hierarchy_level=2, fte_percentage=100)
        )
        p_id = self.pool_repo.create_pool(ResourcePool(name="DevOps Pool"))
        self.pool_repo.create_mapping(
            PoolMapping(pool_id=p_id, target_type="function", target_id=f_id, allocation_pct=100.0)
        )

        # 1. Test get_all_resource_pools alias
        df_all = self.pool_repo.get_all_resource_pools()
        self.assertEqual(len(df_all), 1)
        self.assertEqual(df_all.iloc[0]["name"], "DevOps Pool")

        # 2. Test get_pool_capacity_detail directly on repo
        detail = self.pool_repo.get_pool_capacity_detail(p_id)
        self.assertEqual(detail.pool_id, p_id)
        self.assertEqual(detail.total_capacity_fte, 1.0)

    def test_project_level_and_task_level_deduplication(self) -> None:
        """Verify deduplication between project-level and task-level assignments."""
        f_id = self.org_repo.create_function(
            OrgFunction(name="Principal Architect", hierarchy_level=2, fte_percentage=200)
        )
        p_id = self.pool_repo.create_pool(ResourcePool(name="Architecture Pool"))
        self.pool_repo.create_mapping(
            PoolMapping(pool_id=p_id, target_type="function", target_id=f_id, allocation_pct=100.0)
        )
        # Create Project 50
        self.project_repo.create_project(
            project_id=50,
            name="Architecture Revamp",
            status="In Progress",
            planned_budget=100000.0,
            actual_budget=0.0,
            dynamic_attributes={},
        )
        # Capacity = 2.0 FTE
        cap_detail = self.pool_repo.get_pool_capacity_detail(p_id)
        self.assertEqual(cap_detail.total_capacity_fte, 2.0)

        # Create tasks on project 50
        t1_id = self.milestone_repo.create_milestone(
            project_id=50,
            task_name="Architecture Foundation",
            phase="Discovery",
            start_date="2026-07-01",
            end_date="2026-07-05",
            progress_pct=10,
        )
        t2_id = self.milestone_repo.create_milestone(
            project_id=50,
            task_name="Architecture Implementation",
            phase="Execution",
            start_date="2026-07-06",
            end_date="2026-07-10",
            progress_pct=0,
        )

        # Project-level assignment: 1.5 FTE across 2026-07-01 to 2026-07-10
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=50,
                task_id=None,
                fte_assigned=1.5,
                start_date="2026-07-01",
                end_date="2026-07-10",
                notes="Project-level architecture oversight",
            )
        )

        # Task 1 assignment: 1.0 FTE across 2026-07-01 to 2026-07-05
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=50,
                task_id=t1_id,
                fte_assigned=1.0,
            )
        )

        # Task 2 assignment: 2.0 FTE across 2026-07-06 to 2026-07-10
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=50,
                task_id=t2_id,
                fte_assigned=2.0,
            )
        )

        # Calculate pool status
        detail = ResourcePoolService.calculate_pool_capacity(
            pool_id=p_id,
            org_repo=self.org_repo,
            pool_repo=self.pool_repo,
            milestone_repo=self.milestone_repo,
        )

        # In interval 1 (07-01 to 07-05): max(1.5, 1.0) = 1.5 FTE (NOT 2.5!)
        self.assertEqual(detail.daily_usage["2026-07-01"], 1.5)
        self.assertEqual(detail.daily_usage["2026-07-05"], 1.5)

        # In interval 2 (07-06 to 07-10): max(1.5, 2.0) = 2.0 FTE (NOT 3.5!)
        self.assertEqual(detail.daily_usage["2026-07-06"], 2.0)
        self.assertEqual(detail.daily_usage["2026-07-10"], 2.0)

        # Peak is 2.0 FTE, exactly equal to capacity 2.0 FTE -> NOT overassigned!
        self.assertEqual(detail.peak_assigned_fte, 2.0)
        self.assertFalse(detail.is_overassigned)

        # Now add an extra task assignment to Task 2 of 0.5 FTE -> task level becomes 2.5 FTE
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=50,
                task_id=t2_id,
                fte_assigned=0.5,
            )
        )

        detail_over = ResourcePoolService.calculate_pool_capacity(
            pool_id=p_id,
            org_repo=self.org_repo,
            pool_repo=self.pool_repo,
            milestone_repo=self.milestone_repo,
        )
        # Task level = 2.0 + 0.5 = 2.5 FTE. Project level = 1.5 FTE. max(1.5, 2.5) = 2.5 FTE.
        self.assertEqual(detail_over.daily_usage["2026-07-06"], 2.5)
        self.assertTrue(detail_over.is_overassigned)
        self.assertEqual(detail_over.peak_excess_fte, 0.5)

    def test_project_assignments_map_and_filters(self) -> None:
        """Verify get_project_assignments_map and only_project_level filters."""
        p_id = self.pool_repo.create_pool(ResourcePool(name="PMO Pool"))

        # Create Project 60
        self.project_repo.create_project(
            project_id=60,
            name="PMO Transformation",
            status="In Progress",
            planned_budget=50000.0,
            actual_budget=0.0,
            dynamic_attributes={},
        )
        t_id = self.milestone_repo.create_milestone(
            project_id=60,
            task_name="PMO Setup",
            phase="Setup",
            start_date="2026-08-01",
            end_date="2026-08-15",
            progress_pct=50,
        )

        # Create 1 project-level and 1 task-level assignment
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=60,
                task_id=None,
                fte_assigned=1.5,
                notes="PMO lead",
            )
        )
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=60,
                task_id=t_id,
                fte_assigned=0.5,
                notes="Task support",
            )
        )

        # only_project_level=True
        df_proj_only = self.pool_repo.get_assignments(only_project_level=True)
        self.assertEqual(len(df_proj_only), 1)
        self.assertIsNone(df_proj_only.iloc[0]["task_id"])

        # get_project_assignments_map
        p_map = self.pool_repo.get_project_assignments_map([60])
        self.assertIn(60, p_map)
        self.assertEqual(len(p_map[60]), 1)
        self.assertEqual(p_map[60][0]["pool_name"], "PMO Pool")
        self.assertEqual(p_map[60][0]["fte"], 1.5)

    def test_pool_timeline_figure_rendering(self) -> None:
        """Verify _build_pool_timeline_figure creates valid traces with gap handling."""
        from src.views.settings_view import _build_pool_timeline_figure

        # Create Project 70
        self.project_repo.create_project(
            project_id=70,
            name="Interval Initiative",
            status="In Progress",
            planned_budget=40000.0,
            actual_budget=0.0,
            dynamic_attributes={},
        )

        # Create detail with two separate intervals (gap between them)
        f_id = self.org_repo.create_function(
            OrgFunction(name="Engineer", hierarchy_level=1, fte_percentage=100)
        )
        p_id = self.pool_repo.create_pool(ResourcePool(name="Interval Pool"))
        self.pool_repo.create_mapping(
            PoolMapping(pool_id=p_id, target_type="function", target_id=f_id, allocation_pct=100.0)
        )

        # Assignment 1: 2026-01-01 to 2026-01-03 at 0.5 FTE (within cap 1.0)
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=70,
                task_id=None,
                fte_assigned=0.5,
                start_date="2026-01-01",
                end_date="2026-01-03",
            )
        )
        # Assignment 2: 2026-01-10 to 2026-01-12 at 1.5 FTE (over cap 1.0)
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=70,
                task_id=None,
                fte_assigned=1.5,
                start_date="2026-01-10",
                end_date="2026-01-12",
            )
        )

        detail = ResourcePoolService.calculate_pool_capacity(
            pool_id=p_id,
            org_repo=self.org_repo,
            pool_repo=self.pool_repo,
            milestone_repo=self.milestone_repo,
        )

        fig = _build_pool_timeline_figure(detail)
        self.assertIsNotNone(fig)
        trace_names = [tr.name for tr in fig.data]
        # Should have within cap and over cap traces plus capacity limit
        self.assertIn(t("settings.demand_within_cap"), trace_names)
        self.assertIn(t("settings.demand_over_cap"), trace_names)
        self.assertIn(t("settings.pool_capacity_line"), trace_names)

        # Verify capacity line contains None for the gap between 2026-01-03 and 2026-01-10
        cap_trace = next(tr for tr in fig.data if tr.name == t("settings.pool_capacity_line"))
        self.assertIn(None, list(cap_trace.x))

    def test_project_level_assignment_inherits_project_bounds_not_today(self) -> None:
        """Verify project-level assignment without custom dates inherits project bounds, not today."""
        import datetime

        self.project_repo.create_project(
            project_id=80,
            name="Timeline Initiative",
            status="In Progress",
            planned_budget=75000.0,
            actual_budget=0.0,
            dynamic_attributes={},
        )
        # Create a task defining project bounds from 2026-06-01 to 2026-06-30
        self.milestone_repo.create_milestone(
            project_id=80,
            task_name="Core Milestone",
            phase="Phase 1",
            start_date="2026-06-01",
            end_date="2026-06-30",
            progress_pct=0,
        )

        # Verify get_all_project_date_bounds returns both int and str keys
        bounds = self.milestone_repo.get_all_project_date_bounds()
        self.assertIn(80, bounds)
        self.assertIn("80", bounds)
        self.assertEqual(bounds[80], ("2026-06-01", "2026-06-30"))
        self.assertEqual(bounds["80"], ("2026-06-01", "2026-06-30"))

        f_id = self.org_repo.create_function(
            OrgFunction(name="Consultant", hierarchy_level=1, fte_percentage=100)
        )
        p_id = self.pool_repo.create_pool(ResourcePool(name="Consulting Pool"))
        self.pool_repo.create_mapping(
            PoolMapping(pool_id=p_id, target_type="function", target_id=f_id, allocation_pct=100.0)
        )

        # Project level assignment with NO custom dates (default full duration)
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=80,
                task_id=None,
                fte_assigned=1.0,
                start_date=None,
                end_date=None,
                notes="Advisory",
            )
        )

        detail = ResourcePoolService.calculate_pool_capacity(
            pool_id=p_id,
            org_repo=self.org_repo,
            pool_repo=self.pool_repo,
            milestone_repo=self.milestone_repo,
        )

        self.assertEqual(len(detail.assignments), 1)
        assign = detail.assignments[0]
        # Must resolve to project bounds, not today!
        self.assertEqual(assign["start_date"], "2026-06-01")
        self.assertEqual(assign["end_date"], "2026-06-30")

        # Daily usage must contain 2026-06-01 and 2026-06-30
        self.assertIn("2026-06-01", detail.daily_usage)
        self.assertIn("2026-06-30", detail.daily_usage)
        self.assertEqual(detail.daily_usage["2026-06-01"], 1.0)
        self.assertEqual(detail.daily_usage["2026-06-30"], 1.0)

        # Today should NOT be in daily_usage (unless today happens to be in June 2026)
        today_iso = datetime.date.today().isoformat()
        if today_iso < "2026-06-01" or today_iso > "2026-06-30":
            self.assertNotIn(today_iso, detail.daily_usage)

    def test_resource_grid_payload_and_max_demand_period_calculation(self) -> None:
        """Verify that daily_usage accurately provides period max demand for the resource grid."""
        f_id = self.org_repo.create_function(
            OrgFunction(name="Cloud Architect", hierarchy_level=2, fte_percentage=200)
        )
        p_id = self.pool_repo.create_pool(ResourcePool(name="Cloud Arch Pool"))
        self.pool_repo.create_mapping(
            PoolMapping(pool_id=p_id, target_type="function", target_id=f_id, allocation_pct=100.0)
        )

        self.project_repo.create_project(
            project_id=81,
            name="Cloud Migration Project",
            status="In Progress",
            planned_budget=120000.0,
            actual_budget=0.0,
            dynamic_attributes={},
        )
        t_id_jan = self.milestone_repo.create_milestone(
            project_id=81,
            task_name="Cloud Strategy",
            phase="Analysis",
            start_date="2026-01-10",
            end_date="2026-01-20",
            progress_pct=10,
        )
        t_id_feb = self.milestone_repo.create_milestone(
            project_id=81,
            task_name="Cloud Rollout",
            phase="Execution",
            start_date="2026-02-01",
            end_date="2026-02-15",
            progress_pct=0,
        )

        # Jan assignment: 1.5 FTE (<= 2.0 capacity)
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=81,
                task_id=t_id_jan,
                fte_assigned=1.5,
            )
        )
        # Feb assignment: 2.5 FTE (> 2.0 capacity -> overallocated)
        self.pool_repo.create_assignment(
            PoolAssignment(
                pool_id=p_id,
                project_id=81,
                task_id=t_id_feb,
                fte_assigned=2.5,
            )
        )

        detail = ResourcePoolService.calculate_pool_capacity(
            pool_id=p_id,
            org_repo=self.org_repo,
            pool_repo=self.pool_repo,
            milestone_repo=self.milestone_repo,
        )

        self.assertEqual(detail.total_capacity_fte, 2.0)

        # Helper to simulate JS getMaxDemandForPeriod
        def get_max_demand(start_str: str, end_str: str) -> float:
            return max(
                (fte for d, fte in detail.daily_usage.items() if start_str <= d <= end_str),
                default=0.0,
            )

        # January Month Cell (2026-01-01 -> 2026-01-31): max demand 1.5, not overallocated
        jan_max = get_max_demand("2026-01-01", "2026-01-31")
        self.assertEqual(jan_max, 1.5)
        self.assertFalse(jan_max > detail.total_capacity_fte)

        # February Month Cell (2026-02-01 -> 2026-02-28): max demand 2.5, overallocated (highlighted in red)
        feb_max = get_max_demand("2026-02-01", "2026-02-28")
        self.assertEqual(feb_max, 2.5)
        self.assertTrue(feb_max > detail.total_capacity_fte)

        # March Month Cell (2026-03-01 -> 2026-03-31): max demand 0.0, empty cell
        mar_max = get_max_demand("2026-03-01", "2026-03-31")
        self.assertEqual(mar_max, 0.0)

        # Quarter 1 Cell (2026-01-01 -> 2026-03-31): covers Feb spike, max demand is 2.5, overallocated
        q1_max = get_max_demand("2026-01-01", "2026-03-31")
        self.assertEqual(q1_max, 2.5)
        self.assertTrue(q1_max > detail.total_capacity_fte)

    def test_calculate_pool_scope_daily_usage_and_filter_period(self) -> None:
        """Verify scope daily usage calculation and period project filtering."""
        assignments = [
            {
                "project_id": 101,
                "start_date": "2026-05-01",
                "end_date": "2026-05-15",
                "fte_assigned": 2.0,
            },
            {
                "project_id": 102,
                "start_date": "2026-05-10",
                "end_date": "2026-05-20",
                "fte_assigned": 1.5,
            },
            {
                "project_id": 103,
                "start_date": "2026-06-01",
                "end_date": "2026-06-10",
                "fte_assigned": 3.0,
            },
        ]

        # Test calculate_pool_scope_daily_usage for project 101
        scope_usage_101 = ResourcePoolService.calculate_pool_scope_daily_usage(assignments, [101])
        self.assertEqual(scope_usage_101.get("2026-05-05"), 2.0)
        self.assertNotIn("2026-05-18", scope_usage_101)
        self.assertNotIn("2026-06-05", scope_usage_101)

        # Test calculate_pool_scope_daily_usage for projects 101 and 102
        scope_usage_both = ResourcePoolService.calculate_pool_scope_daily_usage(assignments, [101, 102])
        self.assertEqual(scope_usage_both.get("2026-05-12"), 3.5)
        self.assertEqual(scope_usage_both.get("2026-05-05"), 2.0)
        self.assertEqual(scope_usage_both.get("2026-05-18"), 1.5)
        self.assertNotIn("2026-06-05", scope_usage_both)

        # Test get_projects_consuming_pool_in_period
        # Slot May 2026: projects 101 and 102 overlap
        pids_may = ResourcePoolService.get_projects_consuming_pool_in_period(assignments, "2026-05-01", "2026-05-31")
        self.assertEqual(sorted(pids_may), [101, 102])

        # Slot June 2026: only project 103 overlaps
        pids_june = ResourcePoolService.get_projects_consuming_pool_in_period(assignments, "2026-06-01", "2026-06-30")
        self.assertEqual(sorted(pids_june), [103])

        # Slot July 2026: no project
        pids_july = ResourcePoolService.get_projects_consuming_pool_in_period(assignments, "2026-07-01", "2026-07-31")
        self.assertEqual(pids_july, [])

        # Test timestamp strings with HH:MM:SS and zero-FTE filtering
        assignments_ts = [
            {
                "project_id": 201,
                "start_date": "2026-09-01 00:00:00",
                "end_date": "2026-09-30 23:59:59",
                "fte_assigned": 1.0,
            },
            {
                "project_id": 202,
                "start_date": "2026-09-30 00:00:00",
                "end_date": "2026-10-15 00:00:00",
                "fte_assigned": 2.0,
            },
            {
                "project_id": 203,
                "start_date": "2026-09-05",
                "end_date": "2026-09-20",
                "fte_assigned": 0.0,  # zero fte should be ignored
            },
        ]
        # September period: 201 and 202 overlap on 2026-09-30, 203 has 0 FTE
        pids_sep = ResourcePoolService.get_projects_consuming_pool_in_period(assignments_ts, "2026-09-01", "2026-09-30")
        self.assertEqual(sorted(pids_sep), [201, 202])

        # Boundary test on single day
        pids_single_day = ResourcePoolService.get_projects_consuming_pool_in_period(assignments_ts, "2026-09-30", "2026-09-30")
        self.assertEqual(sorted(pids_single_day), [201, 202])

    def test_multi_year_assignment_daily_usage(self) -> None:
        """Verify that multi-year assignments continue to accumulate daily usage beyond 366 days."""
        daily_map: dict[str, float] = {}
        # Multi-year assignment spanning 2026 to 2034 (e.g. Project 6 / Project 9)
        ResourcePoolService._accumulate_daily_usage(
            daily_map=daily_map,
            start_str="2026-02-18",
            end_str="2034-08-18",
            fte=0.3,
        )
        # Check day 1, day 365, day 400 (Q2 2027), and later years
        self.assertIn("2026-02-18", daily_map)
        self.assertIn("2027-02-18", daily_map)
        self.assertIn("2027-04-01", daily_map)
        self.assertIn("2027-06-30", daily_map)
        self.assertIn("2034-08-18", daily_map)
        self.assertEqual(daily_map["2027-04-01"], 0.3)
        self.assertEqual(daily_map["2027-06-30"], 0.3)

    @patch("streamlit.rerun")
    @patch("streamlit.toast")
    def test_clear_resource_pool_filter_state(
        self, mock_toast: MagicMock, mock_rerun: MagicMock
    ) -> None:
        """Verify that clearing resource pool filter marks pending clear and triggers immediate rerun."""
        import streamlit as st
        from src.views.planning_view import _handle_clear_resource_pool_filter

        # Setup active filter in session_state
        st.session_state["active_resource_pool_filter"] = {
            "pool_id": 1,
            "pool_name": "BIM Specialist",
            "start_date": "2027-04-01",
            "end_date": "2027-06-30",
            "project_ids": [6, 9],
        }
        st.session_state["ms_multi_projects"] = [6, 9]

        _handle_clear_resource_pool_filter([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

        self.assertNotIn("active_resource_pool_filter", st.session_state)
        self.assertTrue(st.session_state.get("pending_clear_resource_pool_filter"))
        mock_toast.assert_called_once_with("Resource pool filter cleared", icon="✖")
        mock_rerun.assert_called_once()

        # Clean up
        st.session_state.pop("pending_clear_resource_pool_filter", None)
        st.session_state.pop("ms_multi_projects", None)


if __name__ == "__main__":
    unittest.main()
