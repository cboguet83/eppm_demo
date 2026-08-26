"""Comprehensive Unit Tests for Task Dependencies and Constraint Validation."""

import os
import shutil
import tempfile
import unittest

from src.database.schema_init import init_db
from src.models.dependency import LinkType, TaskDependency, DependencyViolation
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.project_repo import ProjectRepository
from src.services.milestone_service import MilestoneService


class TestTaskDependencies(unittest.TestCase):
    """Test suite covering Task Dependency rules (FS, FF, SS, SF), day offsets, and persistence."""

    def setUp(self) -> None:
        """Arrange: Initialize temporary test database and repository instances."""
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_dependencies.db")
        init_db(self.db_path)

        self.project_repo = ProjectRepository(self.db_path)
        self.milestone_repo = MilestoneRepository(self.db_path)

        self.project_repo.create_project("PRJ-ALPHA", "Alpha Core", "Active", 100000.0, 50000.0, {})
        self.project_repo.create_project("PRJ-BETA", "Beta Subsystem", "Active", 80000.0, 20000.0, {})

    def tearDown(self) -> None:
        """Clean up temporary database files."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 1. FINISH-TO-START (FS) TESTS
    # --------------------------------------------------------------------------
    def test_finish_to_start_valid_and_violated(self) -> None:
        """Verify Finish-to-Start (FS) constraints: Successor.start >= Predecessor.end + lag."""
        pred = {"id": 1, "task_name": "Requirements", "start_date": "2026-01-01", "end_date": "2026-01-10"}

        # Successor 1: Starts exactly on pred.end (0 lag) -> Valid
        succ_exact = {"id": 2, "task_name": "Design Exact", "start_date": "2026-01-10", "end_date": "2026-01-20"}
        # Successor 2: Starts after pred.end + 2d lag -> Valid (req: >= 2026-01-12, act: 2026-01-13)
        succ_lag_ok = {"id": 3, "task_name": "Design Lag OK", "start_date": "2026-01-13", "end_date": "2026-01-20"}
        # Successor 3: Starts before pred.end + 2d lag -> Violated (req: >= 2026-01-12, act: 2026-01-11)
        succ_lag_fail = {"id": 4, "task_name": "Design Lag Fail", "start_date": "2026-01-11", "end_date": "2026-01-20"}
        # Successor 4: Negative lag (lead time of -2 days) -> Valid (req: >= 2026-01-08, act: 2026-01-08)
        succ_lead_ok = {"id": 5, "task_name": "Design Lead OK", "start_date": "2026-01-08", "end_date": "2026-01-20"}
        # Successor 5: Negative lag (lead time of -2 days) -> Violated (req: >= 2026-01-08, act: 2026-01-07)
        succ_lead_fail = {"id": 6, "task_name": "Design Lead Fail", "start_date": "2026-01-07", "end_date": "2026-01-20"}

        tasks = [pred, succ_exact, succ_lag_ok, succ_lag_fail, succ_lead_ok, succ_lead_fail]
        deps = [
            {"task_id": 2, "predecessor_task_id": 1, "link_type": "FS", "lag_days": 0},
            {"task_id": 3, "predecessor_task_id": 1, "link_type": "FS", "lag_days": 2},
            {"task_id": 4, "predecessor_task_id": 1, "link_type": "FS", "lag_days": 2},
            {"task_id": 5, "predecessor_task_id": 1, "link_type": "FS", "lag_days": -2},
            {"task_id": 6, "predecessor_task_id": 1, "link_type": "FS", "lag_days": -2},
        ]

        evaluated, violations = MilestoneService.evaluate_constraints(tasks, deps)

        self.assertFalse(evaluated[0]["is_violated"])
        self.assertFalse(evaluated[1]["is_violated"])
        self.assertTrue(evaluated[2]["is_violated"])
        self.assertFalse(evaluated[3]["is_violated"])
        self.assertTrue(evaluated[4]["is_violated"])

        self.assertEqual(len(violations[2]), 0)
        self.assertEqual(len(violations[3]), 0)
        self.assertEqual(len(violations[4]), 1)
        self.assertIn("Start must be \u2265 2026-01-12", violations[4][0])
        self.assertEqual(len(violations[5]), 0)
        self.assertEqual(len(violations[6]), 1)
        self.assertIn("Start must be \u2265 2026-01-08", violations[6][0])

    # --------------------------------------------------------------------------
    # 2. FINISH-TO-FINISH (FF) TESTS
    # --------------------------------------------------------------------------
    def test_finish_to_finish_valid_and_violated(self) -> None:
        """Verify Finish-to-Finish (FF) constraints: Successor.end >= Predecessor.end + lag."""
        pred = {"id": 1, "task_name": "Main Development", "start_date": "2026-01-01", "end_date": "2026-01-15"}

        # Successor 1: Ends on pred.end (0 lag) -> Valid
        succ_exact = {"id": 2, "task_name": "Documentation Exact", "start_date": "2026-01-05", "end_date": "2026-01-15"}
        # Successor 2: Ends after pred.end + 3d lag -> Valid (req: >= 2026-01-18, act: 2026-01-19)
        succ_lag_ok = {"id": 3, "task_name": "Documentation Lag OK", "start_date": "2026-01-05", "end_date": "2026-01-19"}
        # Successor 3: Ends before pred.end + 3d lag -> Violated (req: >= 2026-01-18, act: 2026-01-17)
        succ_lag_fail = {"id": 4, "task_name": "Documentation Lag Fail", "start_date": "2026-01-05", "end_date": "2026-01-17"}

        tasks = [pred, succ_exact, succ_lag_ok, succ_lag_fail]
        deps = [
            {"task_id": 2, "predecessor_task_id": 1, "link_type": "FF", "lag_days": 0},
            {"task_id": 3, "predecessor_task_id": 1, "link_type": "FF", "lag_days": 3},
            {"task_id": 4, "predecessor_task_id": 1, "link_type": "FF", "lag_days": 3},
        ]

        evaluated, violations = MilestoneService.evaluate_constraints(tasks, deps)

        self.assertFalse(evaluated[0]["is_violated"])
        self.assertFalse(evaluated[1]["is_violated"])
        self.assertTrue(evaluated[2]["is_violated"])

        self.assertEqual(len(violations[4]), 1)
        self.assertIn("FF with 'Main Development'", violations[4][0])
        self.assertIn("End must be \u2265 2026-01-18", violations[4][0])

    # --------------------------------------------------------------------------
    # 3. START-TO-START (SS) TESTS
    # --------------------------------------------------------------------------
    def test_start_to_start_valid_and_violated(self) -> None:
        """Verify Start-to-Start (SS) constraints: Successor.start >= Predecessor.start + lag."""
        pred = {"id": 1, "task_name": "Data Migration", "start_date": "2026-02-01", "end_date": "2026-02-20"}

        # Successor 1: Starts exactly on pred.start (0 lag) -> Valid
        succ_exact = {"id": 2, "task_name": "Audit Logging", "start_date": "2026-02-01", "end_date": "2026-02-25"}
        # Successor 2: Starts with +5d lag -> Valid (req: >= 2026-02-06, act: 2026-02-07)
        succ_lag_ok = {"id": 3, "task_name": "Parallel Review OK", "start_date": "2026-02-07", "end_date": "2026-02-25"}
        # Successor 3: Starts with +5d lag -> Violated (req: >= 2026-02-06, act: 2026-02-03)
        succ_lag_fail = {"id": 4, "task_name": "Parallel Review Fail", "start_date": "2026-02-03", "end_date": "2026-02-25"}

        tasks = [pred, succ_exact, succ_lag_ok, succ_lag_fail]
        deps = [
            {"task_id": 2, "predecessor_task_id": 1, "link_type": "SS", "lag_days": 0},
            {"task_id": 3, "predecessor_task_id": 1, "link_type": "SS", "lag_days": 5},
            {"task_id": 4, "predecessor_task_id": 1, "link_type": "SS", "lag_days": 5},
        ]

        evaluated, violations = MilestoneService.evaluate_constraints(tasks, deps)

        self.assertFalse(evaluated[0]["is_violated"])
        self.assertFalse(evaluated[1]["is_violated"])
        self.assertTrue(evaluated[2]["is_violated"])

        self.assertEqual(len(violations[4]), 1)
        self.assertIn("SS with 'Data Migration'", violations[4][0])
        self.assertIn("Start must be \u2265 2026-02-06", violations[4][0])

    # --------------------------------------------------------------------------
    # 4. START-TO-FINISH (SF) TESTS
    # --------------------------------------------------------------------------
    def test_start_to_finish_valid_and_violated(self) -> None:
        """Verify Start-to-Finish (SF) constraints: Successor.end >= Predecessor.start + lag."""
        pred = {"id": 1, "task_name": "Legacy Decommission", "start_date": "2026-03-10", "end_date": "2026-03-20"}

        # Successor 1: Ends on pred.start (0 lag) -> Valid
        succ_exact = {"id": 2, "task_name": "Old System Support Exact", "start_date": "2026-03-01", "end_date": "2026-03-10"}
        # Successor 2: Ends with +4d lag -> Valid (req: >= 2026-03-14, act: 2026-03-15)
        succ_lag_ok = {"id": 3, "task_name": "Old System Support Lag OK", "start_date": "2026-03-01", "end_date": "2026-03-15"}
        # Successor 3: Ends before pred.start + 4d lag -> Violated (req: >= 2026-03-14, act: 2026-03-12)
        succ_lag_fail = {"id": 4, "task_name": "Old System Support Lag Fail", "start_date": "2026-03-01", "end_date": "2026-03-12"}

        tasks = [pred, succ_exact, succ_lag_ok, succ_lag_fail]
        deps = [
            {"task_id": 2, "predecessor_task_id": 1, "link_type": "SF", "lag_days": 0},
            {"task_id": 3, "predecessor_task_id": 1, "link_type": "SF", "lag_days": 4},
            {"task_id": 4, "predecessor_task_id": 1, "link_type": "SF", "lag_days": 4},
        ]

        evaluated, violations = MilestoneService.evaluate_constraints(tasks, deps)

        self.assertFalse(evaluated[0]["is_violated"])
        self.assertFalse(evaluated[1]["is_violated"])
        self.assertTrue(evaluated[2]["is_violated"])

        self.assertEqual(len(violations[4]), 1)
        self.assertIn("SF with 'Legacy Decommission'", violations[4][0])
        self.assertIn("End must be \u2265 2026-03-14", violations[4][0])

    # --------------------------------------------------------------------------
    # 5. MULTIPLE CONCURRENT PREDECESSORS ON SINGLE TASK
    # --------------------------------------------------------------------------
    def test_multiple_predecessors_single_task(self) -> None:
        """Verify that a task with multiple predecessors aggregates all constraints correctly."""
        p1 = {"id": 10, "task_name": "DB Setup", "start_date": "2026-01-01", "end_date": "2026-01-10"}
        p2 = {"id": 20, "task_name": "Auth Service", "start_date": "2026-01-05", "end_date": "2026-01-15"}
        p3 = {"id": 30, "task_name": "UI Framework", "start_date": "2026-01-01", "end_date": "2026-01-20"}

        succ = {"id": 40, "task_name": "Integration Hub", "start_date": "2026-01-16", "end_date": "2026-01-30"}

        tasks = [p1, p2, p3, succ]
        deps = [
            {"task_id": 40, "predecessor_task_id": 10, "link_type": "FS", "lag_days": 0},
            {"task_id": 40, "predecessor_task_id": 20, "link_type": "FS", "lag_days": 2},
            {"task_id": 40, "predecessor_task_id": 30, "link_type": "SS", "lag_days": 0},
        ]

        evaluated, violations = MilestoneService.evaluate_constraints(tasks, deps)

        self.assertEqual(len(evaluated), 3)
        self.assertFalse(evaluated[0]["is_violated"])
        self.assertTrue(evaluated[1]["is_violated"])
        self.assertFalse(evaluated[2]["is_violated"])

        self.assertEqual(len(violations[40]), 1)
        self.assertIn("Auth Service", violations[40][0])

    # --------------------------------------------------------------------------
    # 6. EXTERNAL PROJECT CONSTRAINTS (WHOLE PROJECT & SPECIFIC TASKS)
    # --------------------------------------------------------------------------
    def test_external_project_and_task_constraints(self) -> None:
        """Verify linking against whole external project bounds and specific external tasks."""
        internal_task = {"id": 100, "task_name": "Core Integration", "start_date": "2026-04-10", "end_date": "2026-04-25"}

        project_bounds = {
            "PRJ-BETA": ("2026-03-01", "2026-04-15"),
        }

        deps = [
            {"task_id": 100, "predecessor_task_id": None, "predecessor_project_id": "PRJ-BETA", "link_type": "FS", "lag_days": 0},
        ]

        evaluated, violations = MilestoneService.evaluate_constraints([internal_task], deps, project_bounds)

        self.assertEqual(len(evaluated), 1)
        self.assertTrue(evaluated[0]["is_violated"])
        self.assertIn("Project [PRJ-BETA]", evaluated[0]["violation_text"])
        self.assertEqual(len(violations[100]), 1)

    # --------------------------------------------------------------------------
    # 7. DATABASE PERSISTENCE, MIGRATION, AND CASCADE DELETIONS
    # --------------------------------------------------------------------------
    def test_repository_dependencies_lifecycle(self) -> None:
        """Verify creating, querying, updating, and cascading deletions in task_dependencies table."""
        # Create steps
        s1 = self.milestone_repo.create_milestone("PRJ-ALPHA", "Step 1", "Phase 1", "2026-01-01", "2026-01-10", 100)
        s2 = self.milestone_repo.create_milestone("PRJ-ALPHA", "Step 2", "Phase 1", "2026-01-11", "2026-01-20", 50)
        s3 = self.milestone_repo.create_milestone(
            "PRJ-ALPHA",
            "Step 3",
            "Phase 2",
            "2026-01-21",
            "2026-01-30",
            0,
            dependencies=[
                {"predecessor_task_id": s1, "predecessor_project_id": None, "link_type": "FS", "lag_days": 0},
                {"predecessor_task_id": s2, "predecessor_project_id": None, "link_type": "SS", "lag_days": 2},
                {"predecessor_task_id": None, "predecessor_project_id": "PRJ-BETA", "link_type": "FF", "lag_days": 5},
            ],
        )

        deps = self.milestone_repo.get_task_dependencies(s3)
        self.assertEqual(len(deps), 3)

        link_types = {d["link_type"] for d in deps}
        self.assertEqual(link_types, {"FS", "SS", "FF"})

        # Update s3 with a new single dependency (overwriting previous 3)
        self.milestone_repo.update_milestone(
            milestone_id=s3,
            task_name="Step 3 Updated",
            phase="Phase 2",
            start_date="2026-01-22",
            end_date="2026-01-31",
            progress_pct=10,
            dependencies=[
                {"predecessor_task_id": s2, "predecessor_project_id": None, "link_type": "SF", "lag_days": 1},
            ],
        )

        updated_deps = self.milestone_repo.get_task_dependencies(s3)
        self.assertEqual(len(updated_deps), 1)
        self.assertEqual(updated_deps[0]["link_type"], "SF")
        self.assertEqual(updated_deps[0]["lag_days"], 1)

        # Delete predecessor step s2 and verify cascade
        self.milestone_repo.delete_milestone(s2)
        deps_after_pred_delete = self.milestone_repo.get_task_dependencies(s3)
        self.assertEqual(len(deps_after_pred_delete), 0)

        # Delete project PRJ-ALPHA and verify project-wide dependency cleanup
        self.milestone_repo.save_task_dependencies(s3, [{"predecessor_task_id": None, "predecessor_project_id": "PRJ-BETA", "link_type": "FS", "lag_days": 0}])
        self.assertEqual(len(self.milestone_repo.get_task_dependencies(s3)), 1)
        self.project_repo.delete_project("PRJ-ALPHA")
        self.assertEqual(len(self.milestone_repo.get_dependencies_for_project("PRJ-ALPHA")), 0)

    # --------------------------------------------------------------------------
    # 8. MULTI-PROJECT COMBINED CONSTRAINT EVALUATION
    # --------------------------------------------------------------------------
    def test_multiproject_constraint_evaluation(self) -> None:
        """Verify evaluating tasks and dependencies across multiple projects in a single combined timeline."""
        tasks = [
            {"id": 1, "task_name": "P1 Task 1", "start_date": "2026-01-01", "end_date": "2026-01-10", "project_id": "PRJ-1"},
            {"id": 2, "task_name": "P1 Task 2", "start_date": "2026-01-11", "end_date": "2026-01-20", "project_id": "PRJ-1"},
            {"id": 3, "task_name": "P2 Task 1", "start_date": "2026-01-15", "end_date": "2026-01-25", "project_id": "PRJ-2"},
            {"id": 4, "task_name": "P2 Task 2", "start_date": "2026-01-05", "end_date": "2026-01-12", "project_id": "PRJ-2"},
        ]

        deps = [
            # P1 Task 2 depends on P1 Task 1 (Internal: respected)
            {"task_id": 2, "predecessor_task_id": 1, "predecessor_project_id": None, "link_type": "FS", "lag_days": 0},
            # P2 Task 1 depends on P1 Task 2 (Cross-project: violated because P2 Task 1 starts on Jan 15 < P1 Task 2 ends Jan 20)
            {"task_id": 3, "predecessor_task_id": 2, "predecessor_project_id": "PRJ-1", "link_type": "FS", "lag_days": 0},
            # P2 Task 2 depends on whole PRJ-1 (Cross-project whole: violated because PRJ-1 ends Jan 20, but P2 Task 2 starts Jan 5)
            {"task_id": 4, "predecessor_task_id": None, "predecessor_project_id": "PRJ-1", "link_type": "FS", "lag_days": 0},
        ]

        project_bounds = {
            "PRJ-1": ("2026-01-01", "2026-01-20"),
            "PRJ-2": ("2026-01-05", "2026-01-25"),
        }

        evaluated, violations = MilestoneService.evaluate_constraints(tasks, deps, project_bounds)

        self.assertEqual(len(evaluated), 3)
        self.assertFalse(evaluated[0]["is_violated"]) # Task 2 -> Task 1
        self.assertTrue(evaluated[1]["is_violated"])  # Task 3 -> Task 2
        self.assertTrue(evaluated[2]["is_violated"])  # Task 4 -> PRJ-1

        self.assertEqual(len(violations.get(2, [])), 0)
        self.assertEqual(len(violations.get(3, [])), 1)
        self.assertEqual(len(violations.get(4, [])), 1)


if __name__ == "__main__":
    unittest.main()
