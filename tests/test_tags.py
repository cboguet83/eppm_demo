"""Unit tests for Tag domain models, repository, and validation service."""

from app.domain.tags.rules import validate_tag

from app.presentation.components import tag_frames

import os
import tempfile
import unittest

from app.infrastructure.database.schema_init import init_db
from app.domain.resources.models import ResourcePool
from app.domain.tags.rules import validate_tag_group, validate_assignment
from app.domain.tags.models import ProjectTag, ResourcePoolTag, TagDictionary, TagGroup, TaskTag
from app.operator_services import create_planning_service
from app.operator_services import create_project_service
from app.operator_services import create_resource_pool_service
from app.operator_services import create_tag_service


class TestTagsSystem(unittest.TestCase):
    """Test suite for tag groups, tag dictionary, project tags, and task tags."""

    def setUp(self) -> None:
        """Create a temporary database and initialize schemas."""
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()

        init_db(self.db_path)
        self.tag_repo = create_tag_service(self.db_path)
        self.project_repo = create_project_service(self.db_path)
        self.milestone_repo = create_planning_service(self.db_path)
        self.pool_repo = create_resource_pool_service(self.db_path)

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

        df = tag_frames.get_all_tag_groups_frame(self.tag_repo.get_all_tag_groups())
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

        df = tag_frames.get_all_tags_frame(self.tag_repo.get_all_tags())
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

    def test_resource_pool_tags_can_be_replaced_and_cascade(self) -> None:
        """Pools use dictionary tags without duplicates and assignments cascade."""
        pool_id = self.pool_repo.create_pool(ResourcePool(name="Tagged Pool"))
        first_tag = self.tag_repo.create_tag(TagDictionary(tag="Critical"))
        second_tag = self.tag_repo.create_tag(TagDictionary(tag="EMEA"))

        assignment_id = self.tag_repo.create_resource_pool_tag(
            ResourcePoolTag(pool_id=pool_id, tag_id=first_tag)
        )
        duplicate_id = self.tag_repo.create_resource_pool_tag(
            ResourcePoolTag(pool_id=pool_id, tag_id=first_tag)
        )
        self.assertEqual(assignment_id, duplicate_id)

        self.pool_repo.set_pool_tags(pool_id, [first_tag, second_tag, second_tag])
        assigned = tag_frames.get_resource_pool_tags_frame(self.tag_repo.get_resource_pool_tags(pool_id))
        self.assertEqual(set(assigned["tag_id"].astype(int)), {first_tag, second_tag})
        self.assertEqual(self.tag_repo.count_tag_usages(first_tag), 1)

        self.tag_repo.delete_tag(first_tag)
        remaining = tag_frames.get_resource_pool_tags_frame(self.tag_repo.get_resource_pool_tags(pool_id))
        self.assertEqual(remaining["tag_id"].astype(int).tolist(), [second_tag])

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

        df = tag_frames.get_all_project_tags_frame(self.tag_repo.get_all_project_tags())
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

        df = tag_frames.get_all_task_tags_frame(self.tag_repo.get_all_task_tags())
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
        validate_tag_group("Valid Name")
        with self.assertRaises(ValueError):
            validate_tag_group("")
        with self.assertRaises(ValueError):
            validate_tag_group("   ")

        # Tag Dictionary
        validate_tag("Valid Tag")
        with self.assertRaises(ValueError):
            validate_tag("")

        # Project Tag
        validate_assignment(1, 2, None, entity='Project')
        validate_assignment(1, None, 'FreeTag', entity='Project')
        with self.assertRaises(ValueError):
            validate_assignment(None, 2, None, entity='Project')
        with self.assertRaises(ValueError):
            validate_assignment(1, None, '', entity='Project')

        # Task Tag
        validate_assignment(1, 2, None, entity='Task')
        validate_assignment(1, None, 'TaskTag', entity='Task')
        with self.assertRaises(ValueError):
            validate_assignment(None, 2, None, entity='Task')
        with self.assertRaises(ValueError):
            validate_assignment(1, None, '', entity='Task')

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
    # -------------------------------------------------------------------------
    # Group-Specific Tag Queries & Restriction Tests
    # -------------------------------------------------------------------------
    def test_group_specific_tag_queries(self) -> None:
        """Test retrieving tags restricted to 'project_tag' and 'Task_Tag' groups."""
        pt_group_id = self.tag_repo.create_tag_group(TagGroup(tag_group_name="project_tag"))
        tt_group_id = self.tag_repo.create_tag_group(TagGroup(tag_group_name="Task_Tag"))
        other_group_id = self.tag_repo.create_tag_group(TagGroup(tag_group_name="Other_Group"))

        pt_tag_id = self.tag_repo.create_tag(TagDictionary(tag="ProjectSpecificTag", tag_group_id=pt_group_id))
        tt_tag_id = self.tag_repo.create_tag(TagDictionary(tag="TaskSpecificTag", tag_group_id=tt_group_id))
        other_tag_id = self.tag_repo.create_tag(TagDictionary(tag="OtherTag", tag_group_id=other_group_id))

        # 1. Project Tag Group query
        df_pt = tag_frames.get_project_tag_group_tags_frame(self.tag_repo.get_project_tag_group_tags())
        self.assertEqual(len(df_pt), 1)
        self.assertEqual(df_pt.iloc[0]["id"], pt_tag_id)
        self.assertEqual(df_pt.iloc[0]["tag"], "ProjectSpecificTag")

        # 2. Task Tag Group query
        df_tt = tag_frames.get_task_tag_group_tags_frame(self.tag_repo.get_task_tag_group_tags())
        self.assertEqual(len(df_tt), 1)
        self.assertEqual(df_tt.iloc[0]["id"], tt_tag_id)
        self.assertEqual(df_tt.iloc[0]["tag"], "TaskSpecificTag")

        # 3. Validation Service Enforcement
        # Valid Project Tag (from project_tag group)
        validate_assignment(self.project_id, pt_tag_id, None, entity='Project', group=self.tag_repo.get_tag_group_for_tag(pt_tag_id))
        # Invalid Project Tag (from Task_Tag or Other group)
        with self.assertRaises(ValueError):
            validate_assignment(self.project_id, tt_tag_id, None, entity='Project', group=self.tag_repo.get_tag_group_for_tag(tt_tag_id))
        with self.assertRaises(ValueError):
            validate_assignment(self.project_id, other_tag_id, None, entity='Project', group=self.tag_repo.get_tag_group_for_tag(other_tag_id))

        # Valid Task Tag (from Task_Tag group)
        validate_assignment(self.task_id, tt_tag_id, None, entity='Task', group=self.tag_repo.get_tag_group_for_tag(tt_tag_id))
        # Invalid Task Tag (from project_tag or Other group)
        with self.assertRaises(ValueError):
            validate_assignment(self.task_id, pt_tag_id, None, entity='Task', group=self.tag_repo.get_tag_group_for_tag(pt_tag_id))
        with self.assertRaises(ValueError):
            validate_assignment(self.task_id, other_tag_id, None, entity='Task', group=self.tag_repo.get_tag_group_for_tag(other_tag_id))


if __name__ == "__main__":
    unittest.main()
