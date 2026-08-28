"""Unit tests for Tag domain models, repository, and validation service."""

import os
import tempfile
import unittest

from src.database.schema_init import init_db
from src.models.milestone import Milestone
from src.models.project import Project
from src.models.tag import ProjectTag, TagDictionary, TagGroup, TaskTag
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.tag_repo import TagRepository
from src.services.tag_service import TagService


class TestTagsSystem(unittest.TestCase):
    """Test suite for tag groups, tag dictionary, project tags, and task tags."""

    def setUp(self) -> None:
        """Create a temporary database and initialize schemas."""
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()

        init_db(self.db_path)
        self.tag_repo = TagRepository(self.db_path)
        self.project_repo = ProjectRepository(self.db_path)
        self.milestone_repo = MilestoneRepository(self.db_path)

        # Create a sample project and task for tagging tests
        self.project_id = self.project_repo.create_project(
            name="Cloud Platform Alpha",
            status="In Progress",
            planned_budget=500000.0,
        )
        self.task_id = self.milestone_repo.create_milestone(
            project_id=self.project_id,
            task_name="Architecture Blueprint",
            phase="Execution",
            start_date="2026-01-01",
            end_date="2026-06-30",
            progress_pct=50,
        )

    def tearDown(self) -> None:
        """Clean up the temporary database."""
        import gc
        gc.collect()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    # -------------------------------------------------------------------------
    # Tag Group Tests
    # -------------------------------------------------------------------------
    def test_create_and_get_tag_group(self) -> None:
        """Test creating and retrieving tag groups."""
        group_id = self.tag_repo.create_tag_group(TagGroup(tag_group_name="Architecture"))
        self.assertGreater(group_id, 0)

        group = self.tag_repo.get_tag_group_by_id(group_id)
        self.assertIsNotNone(group)
        self.assertEqual(group.tag_group_name, "Architecture")

        df = self.tag_repo.get_all_tag_groups()
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["tag_group_name"], "Architecture")

    def test_update_tag_group(self) -> None:
        """Test updating an existing tag group."""
        group_id = self.tag_repo.create_tag_group(TagGroup(tag_group_name="Arch"))
        success = self.tag_repo.update_tag_group(TagGroup(id=group_id, tag_group_name="Architecture & Systems"))
        self.assertTrue(success)

        group = self.tag_repo.get_tag_group_by_id(group_id)
        self.assertEqual(group.tag_group_name, "Architecture & Systems")

    def test_delete_tag_group(self) -> None:
        """Test deleting a tag group."""
        group_id = self.tag_repo.create_tag_group(TagGroup(tag_group_name="Temp Group"))
        deleted = self.tag_repo.delete_tag_group(group_id)
        self.assertTrue(deleted)
        self.assertIsNone(self.tag_repo.get_tag_group_by_id(group_id))

    # -------------------------------------------------------------------------
    # Tag Dictionary Tests
    # -------------------------------------------------------------------------
    def test_create_and_get_tag(self) -> None:
        """Test creating and retrieving dictionary tags with group associations."""
        group_id = self.tag_repo.create_tag_group(TagGroup(tag_group_name="Tech"))
        tag_id = self.tag_repo.create_tag(TagDictionary(tag="Microservices", tag_group_id=group_id))
        self.assertGreater(tag_id, 0)

        tag = self.tag_repo.get_tag_by_id(tag_id)
        self.assertIsNotNone(tag)
        self.assertEqual(tag.tag, "Microservices")
        self.assertEqual(tag.tag_group_id, group_id)

        df = self.tag_repo.get_all_tags()
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["tag"], "Microservices")
        self.assertEqual(df.iloc[0]["tag_group_name"], "Tech")

    def test_update_tag(self) -> None:
        """Test updating a dictionary tag."""
        tag_id = self.tag_repo.create_tag(TagDictionary(tag="Cloud"))
        success = self.tag_repo.update_tag(TagDictionary(id=tag_id, tag="Cloud Native"))
        self.assertTrue(success)

        tag = self.tag_repo.get_tag_by_id(tag_id)
        self.assertEqual(tag.tag, "Cloud Native")

    def test_delete_tag(self) -> None:
        """Test deleting a dictionary tag."""
        tag_id = self.tag_repo.create_tag(TagDictionary(tag="Legacy"))
        deleted = self.tag_repo.delete_tag(tag_id)
        self.assertTrue(deleted)
        self.assertIsNone(self.tag_repo.get_tag_by_id(tag_id))

    # -------------------------------------------------------------------------
    # Project Tag Assignment Tests
    # -------------------------------------------------------------------------
    def test_create_and_get_project_tag(self) -> None:
        """Test assigning a tag to a project."""
        tag_id = self.tag_repo.create_tag(TagDictionary(tag="Strategic"))
        pt_id = self.tag_repo.create_project_tag(
            ProjectTag(project_id=self.project_id, tag_id=tag_id, free_tag="Priority-1")
        )
        self.assertGreater(pt_id, 0)

        pt = self.tag_repo.get_project_tag_by_id(pt_id)
        self.assertIsNotNone(pt)
        self.assertEqual(pt.project_id, self.project_id)
        self.assertEqual(pt.tag_id, tag_id)
        self.assertEqual(pt.free_tag, "Priority-1")

        df = self.tag_repo.get_all_project_tags()
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["project_name"], "Cloud Platform Alpha")
        self.assertEqual(df.iloc[0]["tag_name"], "Strategic")

    def test_update_and_delete_project_tag(self) -> None:
        """Test updating and deleting a project tag assignment."""
        pt_id = self.tag_repo.create_project_tag(
            ProjectTag(project_id=self.project_id, free_tag="Draft-Tag")
        )
        self.tag_repo.update_project_tag(
            ProjectTag(id=pt_id, project_id=self.project_id, free_tag="Final-Tag")
        )
        pt = self.tag_repo.get_project_tag_by_id(pt_id)
        self.assertEqual(pt.free_tag, "Final-Tag")

        deleted = self.tag_repo.delete_project_tag(pt_id)
        self.assertTrue(deleted)
        self.assertIsNone(self.tag_repo.get_project_tag_by_id(pt_id))

    # -------------------------------------------------------------------------
    # Task Tag Assignment Tests
    # -------------------------------------------------------------------------
    def test_create_and_get_task_tag(self) -> None:
        """Test assigning a tag to a task."""
        tag_id = self.tag_repo.create_tag(TagDictionary(tag="Frontend"))
        tt_id = self.tag_repo.create_task_tag(
            TaskTag(task_id=self.task_id, tag_id=tag_id, free_tag="Urgent-Fix")
        )
        self.assertGreater(tt_id, 0)

        tt = self.tag_repo.get_task_tag_by_id(tt_id)
        self.assertIsNotNone(tt)
        self.assertEqual(tt.task_id, self.task_id)
        self.assertEqual(tt.tag_id, tag_id)
        self.assertEqual(tt.free_tag, "Urgent-Fix")

        df = self.tag_repo.get_all_task_tags()
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["task_name"], "Architecture Blueprint")
        self.assertEqual(df.iloc[0]["tag_name"], "Frontend")

    def test_update_and_delete_task_tag(self) -> None:
        """Test updating and deleting a task tag assignment."""
        tt_id = self.tag_repo.create_task_tag(
            TaskTag(task_id=self.task_id, free_tag="Initial-Task-Tag")
        )
        self.tag_repo.update_task_tag(
            TaskTag(id=tt_id, task_id=self.task_id, free_tag="Reviewed-Task-Tag")
        )
        tt = self.tag_repo.get_task_tag_by_id(tt_id)
        self.assertEqual(tt.free_tag, "Reviewed-Task-Tag")

        deleted = self.tag_repo.delete_task_tag(tt_id)
        self.assertTrue(deleted)
        self.assertIsNone(self.tag_repo.get_task_tag_by_id(tt_id))

    # -------------------------------------------------------------------------
    # Cascade & Constraint Tests
    # -------------------------------------------------------------------------
    def test_cascade_delete_on_project_and_task(self) -> None:
        """Test cascading deletion when projects and tasks are removed."""
        tag_id = self.tag_repo.create_tag(TagDictionary(tag="DevOps"))
        pt_id = self.tag_repo.create_project_tag(ProjectTag(project_id=self.project_id, tag_id=tag_id))
        tt_id = self.tag_repo.create_task_tag(TaskTag(task_id=self.task_id, tag_id=tag_id))

        self.assertEqual(self.tag_repo.count_tag_usages(tag_id), 2)

        # Deleting project cascades to project_tag and project_task -> task_tag
        self.project_repo.delete_project(self.project_id)
        self.assertIsNone(self.tag_repo.get_project_tag_by_id(pt_id))
        self.assertIsNone(self.tag_repo.get_task_tag_by_id(tt_id))
        self.assertEqual(self.tag_repo.count_tag_usages(tag_id), 0)

    def test_cascade_delete_on_dictionary_tag(self) -> None:
        """Test deleting a dictionary tag cascades to project and task tag assignments."""
        tag_id = self.tag_repo.create_tag(TagDictionary(tag="LegacyTech"))
        pt_id = self.tag_repo.create_project_tag(ProjectTag(project_id=self.project_id, tag_id=tag_id))
        tt_id = self.tag_repo.create_task_tag(TaskTag(task_id=self.task_id, tag_id=tag_id))

        self.tag_repo.delete_tag(tag_id)
        self.assertIsNone(self.tag_repo.get_project_tag_by_id(pt_id))
        self.assertIsNone(self.tag_repo.get_task_tag_by_id(tt_id))

    # -------------------------------------------------------------------------
    # Validation Service Tests
    # -------------------------------------------------------------------------
    def test_tag_service_validation(self) -> None:
        """Test TagService validation rules."""
        # Tag Group
        TagService.validate_tag_group("Valid Name")
        with self.assertRaises(ValueError):
            TagService.validate_tag_group("")
        with self.assertRaises(ValueError):
            TagService.validate_tag_group("   ")

        # Tag Dictionary
        TagService.validate_tag("Valid Tag")
        with self.assertRaises(ValueError):
            TagService.validate_tag("")

        # Project Tag
        TagService.validate_project_tag(1, tag_id=2)
        TagService.validate_project_tag(1, free_tag="FreeTag")
        with self.assertRaises(ValueError):
            TagService.validate_project_tag(None, tag_id=2)
        with self.assertRaises(ValueError):
            TagService.validate_project_tag(1, tag_id=None, free_tag="")

        # Task Tag
        TagService.validate_task_tag(1, tag_id=2)
        TagService.validate_task_tag(1, free_tag="TaskTag")
        with self.assertRaises(ValueError):
            TagService.validate_task_tag(None, tag_id=2)
        with self.assertRaises(ValueError):
            TagService.validate_task_tag(1, tag_id=None, free_tag="")

    # -------------------------------------------------------------------------
    # Batch Tag Queries Tests
    # -------------------------------------------------------------------------
    def test_batch_tag_queries(self) -> None:
        """Test batch loading of task tags and project tags."""
        group_id = self.tag_repo.create_tag_group(TagGroup(tag_group_name="Batch Group"))
        tag_id = self.tag_repo.create_tag(TagDictionary(tag="BatchTag", tag_group_id=group_id))

        self.tag_repo.create_project_tag(ProjectTag(project_id=self.project_id, tag_id=tag_id))
        self.tag_repo.create_task_tag(TaskTag(task_id=self.task_id, tag_id=tag_id, free_tag="SpecialTask"))

        # 1. Batch Project Tags
        proj_tags_map = self.tag_repo.get_project_tags_by_project_ids([self.project_id, 999])
        self.assertIn(self.project_id, proj_tags_map)
        self.assertEqual(len(proj_tags_map[self.project_id]), 1)
        self.assertEqual(proj_tags_map[self.project_id][0]["tag_name"], "BatchTag")
        self.assertEqual(proj_tags_map[999], [])

        # 2. Batch Task Tags
        task_tags_map = self.tag_repo.get_task_tags_by_task_ids([self.task_id, 999])
        self.assertIn(self.task_id, task_tags_map)
        self.assertEqual(len(task_tags_map[self.task_id]), 1)
        self.assertEqual(task_tags_map[self.task_id][0]["tag_name"], "BatchTag")
        self.assertEqual(task_tags_map[self.task_id][0]["free_tag"], "SpecialTask")
        self.assertEqual(task_tags_map[999], [])


if __name__ == "__main__":
    unittest.main()

