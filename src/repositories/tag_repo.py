"""Repository for tag groups, dictionary entries, and project/task/pool tags."""

from typing import Any, Optional, Union

import pandas as pd

from src.database.connection import get_db
from src.logging_config import get_logger
from src.models.tag import ProjectTag, ResourcePoolTag, TagDictionary, TagGroup, TaskTag
from src.repositories.project_repo import parse_project_id

logger = get_logger(__name__)


class TagRepository:
    """Encapsulate database operations for the shared tagging system."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initializes the TagRepository.

        Args:
            db_path: Path to SQLite database. If None, uses configured default.
        """
        self.db_path = db_path

    # =========================================================================
    # 1. TAG GROUPS (tag_group)
    # =========================================================================
    def get_all_tag_groups(self) -> pd.DataFrame:
        """Retrieves all tag groups ordered by name.

        Returns:
            pd.DataFrame: DataFrame containing id and tag_group_name.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT id, tag_group_name
                FROM tag_group
                ORDER BY tag_group_name ASC
                """,
                conn,
            )

    def get_tag_group_by_id(self, group_id: int) -> Optional[TagGroup]:
        """Retrieves a single tag group by ID.

        Args:
            group_id: Unique tag group ID.

        Returns:
            Optional[TagGroup]: TagGroup dataclass instance if found, else None.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, tag_group_name FROM tag_group WHERE id = ?",
                (group_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return TagGroup(id=row[0], tag_group_name=row[1])

    def create_tag_group(self, group: TagGroup) -> int:
        """Creates a new tag group record.

        Args:
            group: TagGroup dataclass instance.

        Returns:
            int: Newly created tag group ID.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO tag_group (tag_group_name) VALUES (?)",
                (group.tag_group_name.strip(),),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_tag_group(self, group: TagGroup) -> bool:
        """Updates an existing tag group.

        Args:
            group: TagGroup dataclass instance with id.

        Returns:
            bool: True if updated, False otherwise.
        """
        if group.id is None:
            return False
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tag_group SET tag_group_name = ? WHERE id = ?",
                (group.tag_group_name.strip(), group.id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_tag_group(self, group_id: int) -> bool:
        """Deletes a tag group if no tags in the dictionary reference it.

        Args:
            group_id: Unique tag group ID.

        Returns:
            bool: True if deleted.

        Raises:
            ValueError: If dictionary tags are assigned to this group.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM tag_dictionnary WHERE tag_group_id = ?",
                (group_id,),
            )
            count = cursor.fetchone()[0]
            if count > 0:
                raise ValueError(
                    f"Cannot delete Tag Group (ID: {group_id}): {count} dictionary tags are associated with it."
                )

            cursor.execute("DELETE FROM tag_group WHERE id = ?", (group_id,))
            conn.commit()
            return cursor.rowcount > 0

    def count_tags_by_group(self, group_id: int) -> int:
        """Counts how many dictionary tags are assigned to a tag group.

        Args:
            group_id: Tag group ID.

        Returns:
            int: Number of associated dictionary tags.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM tag_dictionnary WHERE tag_group_id = ?",
                (group_id,),
            )
            return int(cursor.fetchone()[0])

    # =========================================================================
    # 2. TAG DICTIONARY (tag_dictionnary)
    # =========================================================================
    def get_all_tags(self) -> pd.DataFrame:
        """Retrieves all dictionary tags enriched with tag group name.

        Returns:
            pd.DataFrame: DataFrame containing id, tag, tag_group_id, and tag_group_name.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT 
                    td.id,
                    td.tag,
                    td.tag_group_id,
                    tg.tag_group_name
                FROM tag_dictionnary td
                LEFT JOIN tag_group tg ON td.tag_group_id = tg.id
                ORDER BY td.tag ASC
                """,
                conn,
            )

    def get_tags_by_group_name(self, group_name: str) -> pd.DataFrame:
        """Retrieves dictionary tags belonging to tag groups matching the given group name.

        Matching is case-insensitive and normalizes spaces/underscores (e.g. 'project_tag', 'Project Tag').

        Args:
            group_name: Target tag group name identifier.

        Returns:
            pd.DataFrame: DataFrame containing id, tag, tag_group_id, and tag_group_name.
        """
        norm_name = group_name.strip().lower().replace("_", "").replace(" ", "")
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT 
                    td.id,
                    td.tag,
                    td.tag_group_id,
                    tg.tag_group_name
                FROM tag_dictionnary td
                JOIN tag_group tg ON td.tag_group_id = tg.id
                WHERE LOWER(REPLACE(REPLACE(tg.tag_group_name, '_', ''), ' ', '')) = ?
                   OR LOWER(REPLACE(REPLACE(tg.tag_group_name, '_', ''), ' ', '')) = (? || 's')
                ORDER BY td.tag ASC
                """,
                conn,
                params=(norm_name, norm_name),
            )

    def get_project_tag_group_tags(self) -> pd.DataFrame:
        """Retrieves dictionary tags belonging to the 'project_tag' group."""
        return self.get_tags_by_group_name("project_tag")

    def get_task_tag_group_tags(self) -> pd.DataFrame:
        """Retrieves dictionary tags belonging to the 'Task_Tag' group."""
        return self.get_tags_by_group_name("Task_Tag")

    def get_tag_group_for_tag(self, tag_id: int) -> Optional[TagGroup]:
        """Retrieves the TagGroup associated with a specific dictionary tag.

        Args:
            tag_id: Unique dictionary tag ID.

        Returns:
            Optional[TagGroup]: TagGroup dataclass if found, else None.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT tg.id, tg.tag_group_name
                FROM tag_group tg
                JOIN tag_dictionnary td ON td.tag_group_id = tg.id
                WHERE td.id = ?
                """,
                (tag_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return TagGroup(id=row[0], tag_group_name=row[1])

    def get_tag_by_id(self, tag_id: int) -> Optional[TagDictionary]:
        """Retrieves a single tag by ID.

        Args:
            tag_id: Unique tag ID.

        Returns:
            Optional[TagDictionary]: TagDictionary dataclass instance if found.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, tag, tag_group_id FROM tag_dictionnary WHERE id = ?",
                (tag_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return TagDictionary(id=row[0], tag=row[1], tag_group_id=row[2])

    def create_tag(self, tag_item: TagDictionary) -> int:
        """Creates a new dictionary tag record.

        Args:
            tag_item: TagDictionary dataclass instance.

        Returns:
            int: Newly created tag ID.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO tag_dictionnary (tag, tag_group_id) VALUES (?, ?)",
                (tag_item.tag.strip(), tag_item.tag_group_id),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_tag(self, tag_item: TagDictionary) -> bool:
        """Updates an existing dictionary tag.

        Args:
            tag_item: TagDictionary dataclass instance with id.

        Returns:
            bool: True if updated.
        """
        if tag_item.id is None:
            return False
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tag_dictionnary SET tag = ?, tag_group_id = ? WHERE id = ?",
                (tag_item.tag.strip(), tag_item.tag_group_id, tag_item.id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_tag(self, tag_id: int) -> bool:
        """Delete a dictionary tag and all project, task, and pool assignments.

        Args:
            tag_id: Unique tag ID.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM project_tag WHERE tag_id = ?", (tag_id,))
            cursor.execute("DELETE FROM task_tag WHERE tag_id = ?", (tag_id,))
            cursor.execute("DELETE FROM resource_pool_tag WHERE tag_id = ?", (tag_id,))
            cursor.execute("DELETE FROM tag_dictionnary WHERE id = ?", (tag_id,))
            conn.commit()
            return cursor.rowcount > 0

    def count_tag_usages(self, tag_id: int) -> int:
        """Count project, task, and resource-pool references to a tag.

        Args:
            tag_id: Tag ID.

        Returns:
            int: Total usage count across projects, tasks, and resource pools.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 
                    (SELECT COUNT(*) FROM project_tag WHERE tag_id = ?) +
                    (SELECT COUNT(*) FROM task_tag WHERE tag_id = ?) +
                    (SELECT COUNT(*) FROM resource_pool_tag WHERE tag_id = ?)
                """,
                (tag_id, tag_id, tag_id),
            )
            return int(cursor.fetchone()[0])

    # =========================================================================
    # 3. RESOURCE POOL TAGS (resource_pool_tag)
    # =========================================================================
    def get_all_resource_pool_tags(self) -> pd.DataFrame:
        """Return all resource-pool tag assignments with display labels."""
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT
                    rpt.id,
                    rpt.pool_id,
                    rp.name AS pool_name,
                    rpt.tag_id,
                    td.tag AS tag_name,
                    tg.tag_group_name
                FROM resource_pool_tag rpt
                JOIN resource_pool rp ON rp.id = rpt.pool_id
                JOIN tag_dictionnary td ON td.id = rpt.tag_id
                LEFT JOIN tag_group tg ON tg.id = td.tag_group_id
                ORDER BY rp.name ASC, td.tag ASC
                """,
                conn,
            )

    def get_resource_pool_tags(self, pool_id: int) -> pd.DataFrame:
        """Return dictionary tags assigned to one resource pool."""
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT
                    rpt.id,
                    rpt.pool_id,
                    rpt.tag_id,
                    td.tag AS tag_name,
                    tg.tag_group_name
                FROM resource_pool_tag rpt
                JOIN tag_dictionnary td ON td.id = rpt.tag_id
                LEFT JOIN tag_group tg ON tg.id = td.tag_group_id
                WHERE rpt.pool_id = ?
                ORDER BY td.tag ASC
                """,
                conn,
                params=(pool_id,),
            )

    def create_resource_pool_tag(self, pool_tag: ResourcePoolTag) -> int:
        """Assign one dictionary tag to a resource pool, without duplicates."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO resource_pool_tag (pool_id, tag_id)
                VALUES (?, ?)
                ON CONFLICT(pool_id, tag_id) DO NOTHING
                """,
                (pool_tag.pool_id, pool_tag.tag_id),
            )
            cursor.execute(
                "SELECT id FROM resource_pool_tag WHERE pool_id = ? AND tag_id = ?",
                (pool_tag.pool_id, pool_tag.tag_id),
            )
            assignment_id = int(cursor.fetchone()[0])
            conn.commit()
            return assignment_id

    def set_resource_pool_tags(self, pool_id: int, tag_ids: list[int]) -> None:
        """Atomically replace all dictionary tags assigned to a resource pool."""
        normalized_tag_ids = sorted({int(tag_id) for tag_id in tag_ids})
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM resource_pool WHERE id = ?", (pool_id,))
            if cursor.fetchone() is None:
                raise ValueError(f"Resource pool #{pool_id} does not exist.")

            if normalized_tag_ids:
                placeholders = ",".join("?" for _ in normalized_tag_ids)
                cursor.execute(
                    f"SELECT id FROM tag_dictionnary WHERE id IN ({placeholders})",
                    normalized_tag_ids,
                )
                existing_tag_ids = {int(row[0]) for row in cursor.fetchall()}
                missing_tag_ids = set(normalized_tag_ids) - existing_tag_ids
                if missing_tag_ids:
                    raise ValueError(f"Unknown dictionary tag IDs: {sorted(missing_tag_ids)}")

            cursor.execute("DELETE FROM resource_pool_tag WHERE pool_id = ?", (pool_id,))
            cursor.executemany(
                "INSERT INTO resource_pool_tag (pool_id, tag_id) VALUES (?, ?)",
                [(pool_id, tag_id) for tag_id in normalized_tag_ids],
            )
            conn.commit()

    def delete_resource_pool_tag(self, pool_tag_id: int) -> bool:
        """Delete one resource-pool tag assignment."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM resource_pool_tag WHERE id = ?", (pool_tag_id,))
            conn.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # 4. PROJECT TAGS (project_tag)
    # =========================================================================
    def get_all_project_tags(self) -> pd.DataFrame:
        """Retrieves all project tag assignments enriched with project and tag names.

        Returns:
            pd.DataFrame: DataFrame of project tags.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT 
                    pt.id,
                    pt.project_id,
                    p.name AS project_name,
                    pt.tag_id,
                    td.tag AS tag_name,
                    tg.tag_group_name,
                    pt.free_tag
                FROM project_tag pt
                LEFT JOIN project p ON pt.project_id = p.id
                LEFT JOIN tag_dictionnary td ON pt.tag_id = td.id
                LEFT JOIN tag_group tg ON td.tag_group_id = tg.id
                ORDER BY pt.id DESC
                """,
                conn,
            )

    def get_project_tags_by_project(self, project_id: int) -> pd.DataFrame:
        """Retrieves tag assignments for a specific project.

        Args:
            project_id: Project ID.

        Returns:
            pd.DataFrame: Table of tag assignments for the project.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT 
                    pt.id,
                    pt.project_id,
                    pt.tag_id,
                    td.tag AS tag_name,
                    tg.tag_group_name,
                    pt.free_tag
                FROM project_tag pt
                LEFT JOIN tag_dictionnary td ON pt.tag_id = td.id
                LEFT JOIN tag_group tg ON td.tag_group_id = tg.id
                WHERE pt.project_id = ?
                ORDER BY pt.id ASC
                """,
                conn,
                params=(project_id,),
            )

    def get_project_tag_by_id(self, pt_id: int) -> Optional[ProjectTag]:
        """Retrieves a single project tag record by ID.

        Args:
            pt_id: Unique project tag assignment ID.

        Returns:
            Optional[ProjectTag]: ProjectTag dataclass if found.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, project_id, tag_id, free_tag FROM project_tag WHERE id = ?",
                (pt_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return ProjectTag(id=row[0], project_id=row[1], tag_id=row[2], free_tag=row[3])

    def create_project_tag(self, pt: ProjectTag) -> int:
        """Creates a project tag assignment.

        Args:
            pt: ProjectTag dataclass instance.

        Returns:
            int: Newly created project tag assignment ID.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            free_tag_val = pt.free_tag.strip() if pt.free_tag and pt.free_tag.strip() else None
            cursor.execute(
                "INSERT INTO project_tag (project_id, tag_id, free_tag) VALUES (?, ?, ?)",
                (pt.project_id, pt.tag_id, free_tag_val),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_project_tag(self, pt: ProjectTag) -> bool:
        """Updates an existing project tag assignment.

        Args:
            pt: ProjectTag dataclass instance with id.

        Returns:
            bool: True if updated.
        """
        if pt.id is None:
            return False
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            free_tag_val = pt.free_tag.strip() if pt.free_tag and pt.free_tag.strip() else None
            cursor.execute(
                "UPDATE project_tag SET project_id = ?, tag_id = ?, free_tag = ? WHERE id = ?",
                (pt.project_id, pt.tag_id, free_tag_val, pt.id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_project_tag(self, pt_id: int) -> bool:
        """Deletes a project tag assignment.

        Args:
            pt_id: Unique project tag assignment ID.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM project_tag WHERE id = ?", (pt_id,))
            conn.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # 5. TASK TAGS (task_tag)
    # =========================================================================
    def get_all_task_tags(self) -> pd.DataFrame:
        """Retrieves all task tag assignments enriched with task, project, and tag info.

        Returns:
            pd.DataFrame: DataFrame of task tags.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT 
                    tt.id,
                    tt.task_id,
                    ptk.task_name,
                    ptk.project_id,
                    p.name AS project_name,
                    tt.tag_id,
                    td.tag AS tag_name,
                    tg.tag_group_name,
                    tt.free_tag
                FROM task_tag tt
                LEFT JOIN project_task ptk ON tt.task_id = ptk.id
                LEFT JOIN project p ON ptk.project_id = p.id
                LEFT JOIN tag_dictionnary td ON tt.tag_id = td.id
                LEFT JOIN tag_group tg ON td.tag_group_id = tg.id
                ORDER BY tt.id DESC
                """,
                conn,
            )

    def get_task_tags_by_task(self, task_id: int) -> pd.DataFrame:
        """Retrieves tag assignments for a specific task.

        Args:
            task_id: Task ID.

        Returns:
            pd.DataFrame: Table of tag assignments for the task.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT 
                    tt.id,
                    tt.task_id,
                    tt.tag_id,
                    td.tag AS tag_name,
                    tg.tag_group_name,
                    tt.free_tag
                FROM task_tag tt
                LEFT JOIN tag_dictionnary td ON tt.tag_id = td.id
                LEFT JOIN tag_group tg ON td.tag_group_id = tg.id
                WHERE tt.task_id = ?
                ORDER BY tt.id ASC
                """,
                conn,
                params=(task_id,),
            )

    def get_task_tag_by_id(self, tt_id: int) -> Optional[TaskTag]:
        """Retrieves a single task tag record by ID.

        Args:
            tt_id: Unique task tag assignment ID.

        Returns:
            Optional[TaskTag]: TaskTag dataclass if found.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, task_id, tag_id, free_tag FROM task_tag WHERE id = ?",
                (tt_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return TaskTag(id=row[0], task_id=row[1], tag_id=row[2], free_tag=row[3])

    def create_task_tag(self, tt: TaskTag) -> int:
        """Creates a task tag assignment.

        Args:
            tt: TaskTag dataclass instance.

        Returns:
            int: Newly created task tag assignment ID.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            free_tag_val = tt.free_tag.strip() if tt.free_tag and tt.free_tag.strip() else None
            cursor.execute(
                "INSERT INTO task_tag (task_id, tag_id, free_tag) VALUES (?, ?, ?)",
                (tt.task_id, tt.tag_id, free_tag_val),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_task_tag(self, tt: TaskTag) -> bool:
        """Updates an existing task tag assignment.

        Args:
            tt: TaskTag dataclass instance with id.

        Returns:
            bool: True if updated.
        """
        if tt.id is None:
            return False
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            free_tag_val = tt.free_tag.strip() if tt.free_tag and tt.free_tag.strip() else None
            cursor.execute(
                "UPDATE task_tag SET task_id = ?, tag_id = ?, free_tag = ? WHERE id = ?",
                (tt.task_id, tt.tag_id, free_tag_val, tt.id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_task_tag(self, tt_id: int) -> bool:
        """Deletes a task tag assignment.

        Args:
            tt_id: Unique task tag assignment ID.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM task_tag WHERE id = ?", (tt_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_task_tags_by_task_ids(self, task_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        """Retrieves tag assignments grouped by task_id in a single batch query.

        Args:
            task_ids: List of task integer IDs.

        Returns:
            dict[int, list[dict[str, Any]]]: Mapping from task_id to list of tag dicts.
        """
        if not task_ids:
            return {}

        clean_ids = [int(tid) for tid in task_ids if tid is not None]
        if not clean_ids:
            return {}

        placeholders = ",".join("?" for _ in clean_ids)
        result: dict[int, list[dict[str, Any]]] = {tid: [] for tid in clean_ids}
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT 
                    tt.id,
                    tt.task_id,
                    tt.tag_id,
                    td.tag AS tag_name,
                    tg.tag_group_name,
                    tt.free_tag
                FROM task_tag tt
                LEFT JOIN tag_dictionnary td ON tt.tag_id = td.id
                LEFT JOIN tag_group tg ON td.tag_group_id = tg.id
                WHERE tt.task_id IN ({placeholders})
                ORDER BY tt.id ASC
                """,
                clean_ids,
            )
            cols = [col[0] for col in cursor.description]
            for row in cursor.fetchall():
                row_dict = dict(zip(cols, row))
                t_id = row_dict["task_id"]
                if t_id in result:
                    result[t_id].append(row_dict)
        return result

    def get_project_tags_by_project_ids(self, project_ids: list[Union[int, str]]) -> dict[int, list[dict[str, Any]]]:
        """Retrieves tag assignments grouped by project_id in a single batch query.

        Args:
            project_ids: List of project IDs.

        Returns:
            dict[int, list[dict[str, Any]]]: Mapping from project_id to list of tag dicts.
        """
        if not project_ids:
            return {}

        int_ids = [parse_project_id(pid) for pid in project_ids]
        placeholders = ",".join("?" for _ in int_ids)
        result: dict[int, list[dict[str, Any]]] = {pid: [] for pid in int_ids}
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT 
                    pt.id,
                    pt.project_id,
                    pt.tag_id,
                    td.tag AS tag_name,
                    tg.tag_group_name,
                    pt.free_tag
                FROM project_tag pt
                LEFT JOIN tag_dictionnary td ON pt.tag_id = td.id
                LEFT JOIN tag_group tg ON td.tag_group_id = tg.id
                WHERE pt.project_id IN ({placeholders})
                ORDER BY pt.id ASC
                """,
                int_ids,
            )
            cols = [col[0] for col in cursor.description]
            for row in cursor.fetchall():
                row_dict = dict(zip(cols, row))
                p_id = row_dict["project_id"]
                if p_id in result:
                    result[p_id].append(row_dict)
        return result
