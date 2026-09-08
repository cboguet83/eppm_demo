"""SQLite persistence for tag catalogs and assignments."""

from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
import sqlite3
from app.application.exceptions import TagConflictError, TagStorageError
from app.application.ports.tag_records import (
    DictionaryRow,
    EntityChoice,
    PoolTagRow,
    ProjectTagRow,
    TagGroupRow,
    TagLink,
    TaskChoice,
    TaskTagPage,
    TaskTagRow,
)
from app.domain.tags.models import ProjectTag, ResourcePoolTag, TagDictionary, TagGroup, TaskTag
from app.infrastructure.database.connection import get_db
from app.shared.logging import get_logger

logger = get_logger(__name__)


class SqliteTagStore:
    """SQLite tag operations sharing a caller-owned transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Use the gateway-owned connection."""
        self.connection = connection

    def _rows[T](self, model: type[T], query: str, params: Sequence[object] = ()) -> list[T]:
        """Decode SQLite's dynamic row boundary into declared query records."""
        return [model(**dict(row)) for row in self.connection.execute(query, params)]

    def get_all_tag_groups(self) -> list[TagGroupRow]:
        """Retrieves all tag groups ordered by name."""
        conn = self.connection
        return self._rows(
            TagGroupRow,
            """
                SELECT id, tag_group_name, (SELECT COUNT(*) FROM tag_dictionnary WHERE tag_group_id=tag_group.id) AS tag_count
                FROM tag_group
                ORDER BY tag_group_name ASC
                """,
            (),
        )

    def get_tag_group_by_id(self, group_id: int) -> TagGroup | None:
        """Retrieves a single tag group by ID.

        Args:
            group_id: Unique tag group ID.

        Returns:
            TagGroup | None: TagGroup dataclass instance if found, else None.
        """
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("SELECT id, tag_group_name FROM tag_group WHERE id = ?", (group_id,))
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
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tag_group (tag_group_name) VALUES (?)", (group.tag_group_name.strip(),)
        )
        return int(cursor.lastrowid)

    def update_tag_group(self, group: TagGroup) -> bool:
        """Updates an existing tag group.

        Args:
            group: TagGroup dataclass instance with id.

        Returns:
            bool: True if updated, False otherwise.
        """
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tag_group SET tag_group_name = ? WHERE id = ?",
            (group.tag_group_name.strip(), group.id),
        )
        return cursor.rowcount > 0

    def delete_tag_group(self, group_id: int) -> bool:
        """Delete a group after the application checks its references."""
        cursor = self.connection.execute("DELETE FROM tag_group WHERE id=?", (group_id,))
        return cursor.rowcount > 0

    def count_tags_by_group(self, group_id: int) -> int:
        """Counts how many dictionary tags are assigned to a tag group.

        Args:
            group_id: Tag group ID.

        Returns:
            int: Number of associated dictionary tags.
        """
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tag_dictionnary WHERE tag_group_id = ?", (group_id,))
        return int(cursor.fetchone()[0])

    def get_all_tags(self) -> list[DictionaryRow]:
        """Retrieves all dictionary tags enriched with tag group name."""
        conn = self.connection
        return self._rows(
            DictionaryRow,
            """
                SELECT
                    td.id,
                    td.tag,
                    td.tag_group_id,
                    tg.tag_group_name, (SELECT COUNT(*) FROM project_tag WHERE tag_id=td.id) + (SELECT COUNT(*) FROM task_tag WHERE tag_id=td.id) + (SELECT COUNT(*) FROM resource_pool_tag WHERE tag_id=td.id) AS usage_count
                FROM tag_dictionnary td
                LEFT JOIN tag_group tg ON td.tag_group_id = tg.id
                ORDER BY td.tag ASC
                """,
            (),
        )

    def get_tags_by_group_name(self, group_name: str) -> list[DictionaryRow]:
        """Retrieves dictionary tags belonging to tag groups matching the given group name."""
        conn = self.connection
        norm_name = group_name.strip().lower().replace("_", "").replace(" ", "")
        return self._rows(
            DictionaryRow,
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
            (norm_name, norm_name),
        )

    def get_project_tag_group_tags(self) -> list[DictionaryRow]:
        """Retrieves dictionary tags belonging to the 'project_tag' group."""
        return self.get_tags_by_group_name("project_tag")

    def get_task_tag_group_tags(self) -> list[DictionaryRow]:
        """Retrieves dictionary tags belonging to the 'Task_Tag' group."""
        return self.get_tags_by_group_name("Task_Tag")

    def get_tag_group_for_tag(self, tag_id: int) -> TagGroup | None:
        """Retrieves the TagGroup associated with a specific dictionary tag.

        Args:
            tag_id: Unique dictionary tag ID.

        Returns:
            TagGroup | None: TagGroup dataclass if found, else None.
        """
        conn = self.connection
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

    def get_tag_by_id(self, tag_id: int) -> TagDictionary | None:
        """Retrieves a single tag by ID.

        Args:
            tag_id: Unique tag ID.

        Returns:
            TagDictionary | None: TagDictionary dataclass instance if found.
        """
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("SELECT id, tag, tag_group_id FROM tag_dictionnary WHERE id = ?", (tag_id,))
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
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tag_dictionnary (tag, tag_group_id) VALUES (?, ?)",
            (tag_item.tag.strip(), tag_item.tag_group_id),
        )
        return int(cursor.lastrowid)

    def update_tag(self, tag_item: TagDictionary) -> bool:
        """Updates an existing dictionary tag.

        Args:
            tag_item: TagDictionary dataclass instance with id.

        Returns:
            bool: True if updated.
        """
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tag_dictionnary SET tag = ?, tag_group_id = ? WHERE id = ?",
            (tag_item.tag.strip(), tag_item.tag_group_id, tag_item.id),
        )
        return cursor.rowcount > 0

    def delete_tag(self, tag_id: int) -> bool:
        """Delete a dictionary tag and all project, task, and pool assignments.

        Args:
            tag_id: Unique tag ID.

        Returns:
            bool: True if deleted.
        """
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("DELETE FROM project_tag WHERE tag_id = ?", (tag_id,))
        cursor.execute("DELETE FROM task_tag WHERE tag_id = ?", (tag_id,))
        cursor.execute("DELETE FROM resource_pool_tag WHERE tag_id = ?", (tag_id,))
        cursor.execute("DELETE FROM tag_dictionnary WHERE id = ?", (tag_id,))
        return cursor.rowcount > 0

    def count_tag_usages(self, tag_id: int) -> int:
        """Count project, task, and resource-pool references to a tag.

        Args:
            tag_id: Tag ID.

        Returns:
            int: Total usage count across projects, tasks, and resource pools.
        """
        conn = self.connection
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

    def get_all_resource_pool_tags(self) -> list[PoolTagRow]:
        """Return all resource-pool tag assignments with display labels."""
        conn = self.connection
        return self._rows(
            PoolTagRow,
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
            (),
        )

    def get_resource_pool_tags(self, pool_id: int) -> list[PoolTagRow]:
        """Return dictionary tags assigned to one resource pool."""
        conn = self.connection
        return self._rows(
            PoolTagRow,
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
            (pool_id,),
        )

    def create_resource_pool_tag(self, pool_tag: ResourcePoolTag) -> int:
        """Assign one dictionary tag to a resource pool, without duplicates."""
        conn = self.connection
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
        return assignment_id

    def delete_resource_pool_tag(self, pool_tag_id: int) -> bool:
        """Delete one resource-pool tag assignment."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("DELETE FROM resource_pool_tag WHERE id = ?", (pool_tag_id,))
        return cursor.rowcount > 0

    def get_all_project_tags(self) -> list[ProjectTagRow]:
        """Retrieves all project tag assignments enriched with project and tag names."""
        conn = self.connection
        return self._rows(
            ProjectTagRow,
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
            (),
        )

    def get_project_tags_by_project(self, project_id: int) -> list[ProjectTagRow]:
        """Retrieves tag assignments for a specific project."""
        conn = self.connection
        return self._rows(
            ProjectTagRow,
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
            (project_id,),
        )

    def get_project_tag_by_id(self, pt_id: int) -> ProjectTag | None:
        """Retrieves a single project tag record by ID.

        Args:
            pt_id: Unique project tag assignment ID.

        Returns:
            ProjectTag | None: ProjectTag dataclass if found.
        """
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, project_id, tag_id, free_tag FROM project_tag WHERE id = ?", (pt_id,)
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
        conn = self.connection
        cursor = conn.cursor()
        free_tag_val = pt.free_tag.strip() if pt.free_tag and pt.free_tag.strip() else None
        cursor.execute(
            "INSERT INTO project_tag (project_id, tag_id, free_tag) VALUES (?, ?, ?)",
            (pt.project_id, pt.tag_id, free_tag_val),
        )
        return int(cursor.lastrowid)

    def update_project_tag(self, pt: ProjectTag) -> bool:
        """Updates an existing project tag assignment.

        Args:
            pt: ProjectTag dataclass instance with id.

        Returns:
            bool: True if updated.
        """
        conn = self.connection
        cursor = conn.cursor()
        free_tag_val = pt.free_tag.strip() if pt.free_tag and pt.free_tag.strip() else None
        cursor.execute(
            "UPDATE project_tag SET project_id = ?, tag_id = ?, free_tag = ? WHERE id = ?",
            (pt.project_id, pt.tag_id, free_tag_val, pt.id),
        )
        return cursor.rowcount > 0

    def delete_project_tag(self, pt_id: int) -> bool:
        """Deletes a project tag assignment.

        Args:
            pt_id: Unique project tag assignment ID.

        Returns:
            bool: True if deleted.
        """
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("DELETE FROM project_tag WHERE id = ?", (pt_id,))
        return cursor.rowcount > 0

    def get_task_tags_page(
        self,
        *,
        page: int = 1,
        page_size: int = 100,
        search: str = "",
        filters: dict[str, object] | None = None,
        sort: str = "id",
        ascending: bool = False,
    ) -> TaskTagPage:
        """Fetch only one page; search and column filters cover the whole table."""
        conn = self.connection
        columns = {
            "id": "tt.id",
            "task_name": "ptk.task_name",
            "project_name": "p.name",
            "tag_name": "td.tag",
            "tag_group_name": "tg.tag_group_name",
            "free_tag": "tt.free_tag",
        }
        joins = "FROM task_tag tt LEFT JOIN project_task ptk ON tt.task_id=ptk.id LEFT JOIN project p ON ptk.project_id=p.id LEFT JOIN tag_dictionnary td ON tt.tag_id=td.id LEFT JOIN tag_group tg ON td.tag_group_id=tg.id "
        conditions, params = ([], [])
        if search.strip():
            conditions.append(
                "("
                + " OR ".join(
                    (
                        f"instr(lower(COALESCE({column},'')),lower(?))>0"
                        for column in columns.values()
                    )
                )
                + ")"
            )
            params.extend([search.strip()] * len(columns))
        for key, value in (filters or {}).items():
            if key in columns and str(value or "").strip():
                conditions.append(f"instr(lower(COALESCE({columns[key]},'')),lower(?))>0")
                params.append(str(value).strip())
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        order = columns.get(sort, "tt.id")
        direction = "ASC" if ascending else "DESC"
        page_size = max(1, min(200, int(page_size)))
        total = conn.execute("SELECT COUNT(*) FROM task_tag").fetchone()[0]
        filtered_total = (
            conn.execute("SELECT COUNT(*) " + joins + where, params).fetchone()[0]
            if conditions
            else total
        )
        pages = max(1, (filtered_total + page_size - 1) // page_size)
        page = max(1, min(pages, int(page)))
        rows = self._rows(
            TaskTagRow,
            "SELECT tt.id,tt.task_id,ptk.task_name,ptk.project_id,p.name AS project_name,tt.tag_id,td.tag AS tag_name,tg.tag_group_name,tt.free_tag "
            + joins
            + where
            + f" ORDER BY {order} COLLATE NOCASE {direction},tt.id {direction} LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        )
        return TaskTagPage(rows, total, filtered_total, page, pages, page_size)

    def get_all_task_tags(self) -> list[TaskTagRow]:
        """Retrieves all task tag assignments enriched with task, project, and tag info."""
        conn = self.connection
        return self._rows(
            TaskTagRow,
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
            (),
        )

    def get_task_tags_by_task(self, task_id: int) -> list[TaskTagRow]:
        """Retrieves tag assignments for a specific task."""
        conn = self.connection
        return self._rows(
            TaskTagRow,
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
            (task_id,),
        )

    def get_task_tag_by_id(self, tt_id: int) -> TaskTag | None:
        """Retrieves a single task tag record by ID.

        Args:
            tt_id: Unique task tag assignment ID.

        Returns:
            TaskTag | None: TaskTag dataclass if found.
        """
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("SELECT id, task_id, tag_id, free_tag FROM task_tag WHERE id = ?", (tt_id,))
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
        conn = self.connection
        cursor = conn.cursor()
        free_tag_val = tt.free_tag.strip() if tt.free_tag and tt.free_tag.strip() else None
        cursor.execute(
            "INSERT INTO task_tag (task_id, tag_id, free_tag) VALUES (?, ?, ?)",
            (tt.task_id, tt.tag_id, free_tag_val),
        )
        return int(cursor.lastrowid)

    def update_task_tag(self, tt: TaskTag) -> bool:
        """Updates an existing task tag assignment.

        Args:
            tt: TaskTag dataclass instance with id.

        Returns:
            bool: True if updated.
        """
        conn = self.connection
        cursor = conn.cursor()
        free_tag_val = tt.free_tag.strip() if tt.free_tag and tt.free_tag.strip() else None
        cursor.execute(
            "UPDATE task_tag SET task_id = ?, tag_id = ?, free_tag = ? WHERE id = ?",
            (tt.task_id, tt.tag_id, free_tag_val, tt.id),
        )
        return cursor.rowcount > 0

    def delete_task_tag(self, tt_id: int) -> bool:
        """Deletes a task tag assignment.

        Args:
            tt_id: Unique task tag assignment ID.

        Returns:
            bool: True if deleted.
        """
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("DELETE FROM task_tag WHERE id = ?", (tt_id,))
        return cursor.rowcount > 0

    def get_task_tags_by_task_ids(self, task_ids: list[int]) -> dict[int, list[TagLink]]:
        """Retrieves tag assignments grouped by task_id in a single batch query.

        Args:
            task_ids: List of task integer IDs.

        Returns:
            dict[int, list[TagLink]]: Mapping from task_id to list of tag dicts.
        """
        conn = self.connection
        if not task_ids:
            return {}
        clean_ids = [int(tid) for tid in task_ids if tid is not None]
        if not clean_ids:
            return {}
        placeholders = ",".join(("?" for _ in clean_ids))
        result: dict[int, list[TagLink]] = {tid: [] for tid in clean_ids}
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

    def get_project_tags_by_project_ids(self, project_ids: list[int]) -> dict[int, list[TagLink]]:
        """Retrieves tag assignments grouped by project_id in a single batch query.

        Args:
            project_ids: List of project IDs.

        Returns:
            dict[int, list[TagLink]]: Mapping from project_id to list of tag dicts.
        """
        conn = self.connection
        if not project_ids:
            return {}
        int_ids = [int(pid) for pid in project_ids]
        placeholders = ",".join(("?" for _ in int_ids))
        result: dict[int, list[TagLink]] = {pid: [] for pid in int_ids}
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

    def project_choices(self) -> list[EntityChoice]:
        """Read only IDs and labels needed by project-tag selectors."""
        return self._rows(EntityChoice, "SELECT id,name FROM project ORDER BY id")

    def search_task_choices(self, search: str = "", *, limit: int = 50) -> list[TaskChoice]:
        """Read a bounded task selector page, including exact #ID searches."""
        search = search.strip()
        if search.lstrip("#").isdigit():
            where, params = ("WHERE t.id=?", [int(search.lstrip("#"))])
        elif search:
            where, params = (
                "WHERE instr(lower(t.task_name),lower(?))>0 OR instr(lower(p.name),lower(?))>0",
                [search, search],
            )
        else:
            where, params = ("", [])
        return self._rows(
            TaskChoice,
            "SELECT t.id,t.task_name,t.project_id,p.name AS project_name FROM project_task t JOIN project p ON p.id=t.project_id "
            + where
            + " ORDER BY t.id DESC LIMIT ?",
            params + [max(1, min(100, int(limit)))],
        )

    def get_task_choice(self, task_id: int) -> TaskChoice | None:
        """Include a currently assigned task even when outside the search page."""
        rows = self.search_task_choices(f"#{task_id}")
        return rows[0] if rows else None


class SqliteTagGateway:
    """Own connection cleanup, transaction boundaries, and safe errors."""

    def __init__(self, db_path: str | None = None) -> None:
        """Retain the path without opening a connection."""
        self.db_path = db_path

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[SqliteTagStore]:
        """Reserve writes before reference checks and commit or roll back once."""
        try:
            with closing(get_db(self.db_path)) as connection:
                connection.row_factory = sqlite3.Row
                with connection:
                    connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                    yield SqliteTagStore(connection)
        except sqlite3.IntegrityError as exc:
            raise TagConflictError(
                "The tag change conflicts with an existing reference or constraint."
            ) from exc
        except sqlite3.DatabaseError as exc:
            logger.error("Tag storage operation failed (%s)", type(exc).__name__)
            raise TagStorageError("Tag data could not be accessed. Please try again.") from exc
