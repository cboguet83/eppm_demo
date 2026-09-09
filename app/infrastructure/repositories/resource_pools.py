"""SQLite adapter for resource-pool queries and caller-owned writes."""

from collections.abc import Collection
from app.domain.access.models import Permission


from app.application.services.business_access import BusinessAccess
from collections.abc import Iterator
from contextlib import closing, contextmanager
import sqlite3

from app.application.exceptions import ResourcePoolConflictError, ResourcePoolStorageError
from app.domain.resources.models import (
    AssignmentLink,
    AssignmentRow,
    PoolAssignment,
    PoolGroupMemberRow,
    PoolMapping,
    PoolTag,
    PoolTagChoice,
    ResourcePool,
    ResourcePoolGroup,
    ResourcePoolGroupMember,
)
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.business_security import authorized_business_transaction
from app.shared.logging import get_logger

logger = get_logger(__name__)


class SqliteResourcePoolStore:
    """SQL operations sharing the gateway's connection and transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Use the connection owned by the application operation."""
        self.connection = connection

    def get_all_pools(self) -> list[ResourcePool]:
        """Retrieves all resource pools ordered by name."""
        conn = self.connection
        return [
            ResourcePool(**dict(row))
            for row in conn.execute(
                """
            SELECT id, name, description, capacity_fte, created_at
            FROM resource_pool
            ORDER BY name ASC
            """,
                (),
            )
        ]

    def get_pool_by_id(self, pool_id: int) -> ResourcePool | None:
        """Retrieves a single resource pool by primary key ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name, description, capacity_fte, created_at
            FROM resource_pool
            WHERE id = ?
            """,
            (pool_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return ResourcePool(
            id=row[0],
            name=row[1],
            description=row[2] or "",
            capacity_fte=float(row[3]) if row[3] is not None else None,
            created_at=row[4],
        )

    def create_pool(self, pool: ResourcePool) -> int:
        """Creates a new resource pool record."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO main.resource_pool (name, description, capacity_fte)
            VALUES (?, ?, ?)
            """,
            (pool.name.strip(), pool.description.strip(), pool.capacity_fte),
        )
        return int(cursor.lastrowid)

    def update_pool(self, pool: ResourcePool) -> bool:
        """Updates an existing resource pool record."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE main.resource_pool
            SET name = ?, description = ?, capacity_fte = ?
            WHERE id = ?
            """,
            (pool.name.strip(), pool.description.strip(), pool.capacity_fte, pool.id),
        )
        return cursor.rowcount > 0

    def delete_pool(self, pool_id: int) -> bool:
        """Deletes a resource pool by ID (cascades mappings and assignments)."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("DELETE FROM main.resource_pool WHERE id = ?", (pool_id,))
        return cursor.rowcount > 0

    def get_all_group_members(self) -> list[ResourcePoolGroupMember]:
        """Load the complete hierarchy in one query, including shared children."""
        conn = self.connection
        return [
            ResourcePoolGroupMember(**dict(row))
            for row in conn.execute(
                "SELECT group_id,pool_id,child_group_id FROM resource_pool_group_member", ()
            )
        ]

    def get_pool_group_by_id(self, group_id: int) -> ResourcePoolGroup | None:
        """Return one pool group by ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name, description, created_at
            FROM resource_pool_group
            WHERE id = ?
            """,
            (group_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return ResourcePoolGroup(
            id=int(row[0]),
            name=str(row[1]),
            description=str(row[2] or ""),
            created_at=row[3],
        )

    def create_pool_group(self, group: ResourcePoolGroup) -> int:
        """Create an empty pool group."""
        conn = self.connection
        name = group.name.strip()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO main.resource_pool_group (name, description) VALUES (?, ?)",
            (name, group.description.strip()),
        )
        return int(cursor.lastrowid)

    def update_pool_group(self, group: ResourcePoolGroup) -> bool:
        """Update a pool group's name and description."""
        conn = self.connection
        name = group.name.strip()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE main.resource_pool_group
            SET name = ?, description = ?
            WHERE id = ?
            """,
            (name, group.description.strip(), group.id),
        )
        return cursor.rowcount > 0

    def delete_pool_group(self, group_id: int) -> bool:
        """Delete a group and cascade all memberships that reference it."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("DELETE FROM main.resource_pool_group WHERE id = ?", (group_id,))
        return cursor.rowcount > 0

    def get_group_members(self, group_id: int) -> list[PoolGroupMemberRow]:
        """Return the direct pool and child-group members of a group."""
        conn = self.connection
        return [
            PoolGroupMemberRow(**dict(row))
            for row in conn.execute(
                """
            SELECT
                gm.id,
                gm.group_id,
                gm.pool_id,
                gm.child_group_id,
                CASE WHEN gm.pool_id IS NOT NULL THEN 'pool' ELSE 'group' END AS member_type,
                COALESCE(rp.name, child.name) AS member_name
            FROM resource_pool_group_member gm
            LEFT JOIN resource_pool rp ON rp.id = gm.pool_id
            LEFT JOIN resource_pool_group child ON child.id = gm.child_group_id
            WHERE gm.group_id = ?
            ORDER BY member_type ASC, member_name ASC
            """,
                (group_id,),
            )
        ]

    def get_mappings_by_pool(self, pool_id: int) -> list[PoolMapping]:
        """Retrieves all team and function mappings for a given resource pool."""
        conn = self.connection
        return [
            PoolMapping(**dict(row))
            for row in conn.execute(
                """
            SELECT id, pool_id, target_type, target_id, allocation_pct
            FROM resource_pool_mapping
            WHERE pool_id = ?
            ORDER BY target_type ASC, target_id ASC
            """,
                (pool_id,),
            )
        ]

    def get_all_mappings(self) -> list[PoolMapping]:
        """Retrieves all resource pool mappings across the portfolio."""
        conn = self.connection
        return [
            PoolMapping(**dict(row))
            for row in conn.execute(
                """
            SELECT id, pool_id, target_type, target_id, allocation_pct
            FROM resource_pool_mapping
            ORDER BY pool_id ASC, target_type ASC
            """,
                (),
            )
        ]

    def create_mapping(self, mapping: PoolMapping) -> int:
        """Creates or replaces a team/function mapping to a resource pool."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO main.resource_pool_mapping (pool_id, target_type, target_id, allocation_pct)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(pool_id, target_type, target_id)
            DO UPDATE SET allocation_pct = excluded.allocation_pct
            """,
            (
                mapping.pool_id,
                mapping.target_type.strip().lower(),
                mapping.target_id,
                float(mapping.allocation_pct),
            ),
        )
        return int(
            conn.execute(
                "SELECT id FROM resource_pool_mapping WHERE pool_id=? AND target_type=? AND target_id=?",
                (mapping.pool_id, mapping.target_type.strip().lower(), mapping.target_id),
            ).fetchone()[0]
        )

    def update_mapping(self, mapping_id: int, allocation_pct: float) -> bool:
        """Updates the allocation percentage for an existing mapping."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE main.resource_pool_mapping
            SET allocation_pct = ?
            WHERE id = ?
            """,
            (float(allocation_pct), mapping_id),
        )
        return cursor.rowcount > 0

    def delete_mapping(self, mapping_id: int) -> bool:
        """Deletes a pool mapping by ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("DELETE FROM main.resource_pool_mapping WHERE id = ?", (mapping_id,))
        return cursor.rowcount > 0

    def get_assignments(
        self,
        pool_id: int | None = None,
        project_id: int | None = None,
        task_id: int | None = None,
        only_project_level: bool = False,
    ) -> list[AssignmentRow]:
        """Retrieves resource pool assignments with optional filters."""
        conn = self.connection
        query = """
            SELECT 
                rpa.id,
                rpa.pool_id,
                rp.name AS pool_name,
                rpa.project_id,
                p.name AS project_name,
                rpa.task_id,
                pt.task_name,
                pt.start_date AS task_start_date,
                pt.end_date AS task_end_date,
                rpa.fte_assigned,
                rpa.start_date AS custom_start_date,
                rpa.end_date AS custom_end_date,
                COALESCE(rpa.start_date, pt.start_date) AS effective_start_date,
                COALESCE(rpa.end_date, pt.end_date) AS effective_end_date,
                rpa.notes
            FROM resource_pool_assignment rpa
            JOIN resource_pool rp ON rpa.pool_id = rp.id
            JOIN project p ON rpa.project_id = p.id
            LEFT JOIN project_task pt ON rpa.task_id = pt.id
            WHERE 1=1
        """
        params: list[int] = []
        if pool_id is not None:
            query += " AND rpa.pool_id = ?"
            params.append(pool_id)
        if project_id is not None:
            query += " AND rpa.project_id = ?"
            params.append(project_id)
        if only_project_level:
            query += " AND rpa.task_id IS NULL"
        elif task_id is not None:
            query += " AND rpa.task_id = ?"
            params.append(task_id)

        query += " ORDER BY rpa.pool_id ASC, rpa.project_id ASC, rpa.task_id ASC"

        return [dict(row) for row in conn.execute(query, params)]

    def get_assignment_by_id(self, assignment_id: int) -> PoolAssignment | None:
        """Retrieves a single assignment by primary key ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, pool_id, project_id, task_id, fte_assigned, start_date, end_date, notes
            FROM resource_pool_assignment
            WHERE id = ?
            """,
            (assignment_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return PoolAssignment(
            id=row[0],
            pool_id=row[1],
            project_id=row[2],
            task_id=row[3],
            fte_assigned=float(row[4]),
            start_date=row[5],
            end_date=row[6],
            notes=row[7] or "",
        )

    def create_assignment(self, assignment: PoolAssignment) -> int:
        """Creates a new pool assignment to a project or task."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO main.resource_pool_assignment (pool_id, project_id, task_id, fte_assigned, start_date, end_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assignment.pool_id,
                assignment.project_id,
                assignment.task_id,
                float(assignment.fte_assigned),
                assignment.start_date,
                assignment.end_date,
                assignment.notes.strip(),
            ),
        )
        return int(cursor.lastrowid)

    def update_assignment(self, assignment: PoolAssignment) -> bool:
        """Updates an existing pool assignment record."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE main.resource_pool_assignment
            SET pool_id = ?, project_id = ?, task_id = ?, fte_assigned = ?, start_date = ?, end_date = ?, notes = ?
            WHERE id = ?
            """,
            (
                assignment.pool_id,
                assignment.project_id,
                assignment.task_id,
                float(assignment.fte_assigned),
                assignment.start_date,
                assignment.end_date,
                assignment.notes.strip(),
                assignment.id,
            ),
        )
        return cursor.rowcount > 0

    def delete_assignment(self, assignment_id: int) -> bool:
        """Deletes a pool assignment by ID."""
        conn = self.connection
        cursor = conn.cursor()
        cursor.execute("DELETE FROM main.resource_pool_assignment WHERE id = ?", (assignment_id,))
        return cursor.rowcount > 0

    def get_task_assignments_map(self, task_ids: list[int]) -> dict[int, list[AssignmentLink]]:
        """Retrieves pool assignments grouped by task_id in a single query."""
        conn = self.connection
        if not task_ids:
            return {}
        placeholders = ",".join("?" for _ in task_ids)
        query = f"""
            SELECT 
                rpa.id,
                rpa.pool_id,
                rp.name AS pool_name,
                rpa.task_id,
                rpa.fte_assigned,
                rpa.start_date,
                rpa.end_date
            FROM resource_pool_assignment rpa
            JOIN resource_pool rp ON rpa.pool_id = rp.id
            WHERE rpa.task_id IN ({placeholders})
            ORDER BY rp.name ASC
        """
        result: dict[int, list[AssignmentLink]] = {}
        cursor = conn.cursor()
        cursor.execute(query, task_ids)
        for row in cursor.fetchall():
            tid = int(row[3])
            result.setdefault(tid, []).append(
                {
                    "id": int(row[0]),
                    "pool_id": int(row[1]),
                    "pool_name": str(row[2]),
                    "fte": float(row[4]),
                    "start_date": row[5],
                    "end_date": row[6],
                }
            )
        return result

    def get_project_assignments_map(
        self, project_ids: list[int]
    ) -> dict[int, list[AssignmentLink]]:
        """Retrieves project-level pool assignments grouped by project_id in a single query."""
        conn = self.connection
        if not project_ids:
            return {}
        placeholders = ",".join("?" for _ in project_ids)
        query = f"""
            SELECT 
                rpa.id,
                rpa.pool_id,
                rp.name AS pool_name,
                rpa.project_id,
                rpa.fte_assigned,
                rpa.start_date,
                rpa.end_date
            FROM resource_pool_assignment rpa
            JOIN resource_pool rp ON rpa.pool_id = rp.id
            WHERE rpa.task_id IS NULL AND rpa.project_id IN ({placeholders})
            ORDER BY rp.name ASC
        """
        result: dict[int, list[AssignmentLink]] = {}
        cursor = conn.cursor()
        cursor.execute(query, project_ids)
        for row in cursor.fetchall():
            pid = int(row[3])
            result.setdefault(pid, []).append(
                {
                    "id": int(row[0]),
                    "pool_id": int(row[1]),
                    "pool_name": str(row[2]),
                    "fte": float(row[4]),
                    "start_date": row[5],
                    "end_date": row[6],
                }
            )
        return result

    def groups(self) -> list[ResourcePoolGroup]:
        """Load the group catalog without opening per-group connections."""
        return [
            ResourcePoolGroup(**dict(row))
            for row in self.connection.execute(
                "SELECT id,name,description,created_at FROM resource_pool_group ORDER BY name"
            )
        ]

    def replace_group_members(
        self, group_id: int, pool_ids: list[int], child_ids: list[int]
    ) -> None:
        """Replace validated group edges in the surrounding write transaction."""
        self.connection.execute(
            "DELETE FROM main.resource_pool_group_member WHERE group_id=?", (group_id,)
        )
        self.connection.executemany(
            "INSERT INTO main.resource_pool_group_member(group_id,pool_id,child_group_id) VALUES(?,?,?)",
            [(group_id, pool_id, None) for pool_id in pool_ids]
            + [(group_id, None, child_id) for child_id in child_ids],
        )

    def get_tag_choices(self) -> list[PoolTagChoice]:
        """Read the existing tag dictionary for pool editing."""
        return [
            PoolTagChoice(**dict(row))
            for row in self.connection.execute(
                "SELECT td.id,td.tag,td.tag_group_id,tg.tag_group_name "
                "FROM tag_dictionnary td LEFT JOIN tag_group tg ON tg.id=td.tag_group_id ORDER BY td.tag"
            )
        ]

    def get_pool_tags(self, pool_id: int) -> list[PoolTag]:
        """Read tags attached to one pool in display order."""
        return [
            PoolTag(**dict(row))
            for row in self.connection.execute(
                "SELECT rpt.id,rpt.pool_id,rpt.tag_id,td.tag AS tag_name,tg.tag_group_name "
                "FROM resource_pool_tag rpt JOIN tag_dictionnary td ON td.id=rpt.tag_id "
                "LEFT JOIN tag_group tg ON tg.id=td.tag_group_id WHERE rpt.pool_id=? ORDER BY td.tag",
                (pool_id,),
            )
        ]

    def set_pool_tags(self, pool_id: int, tag_ids: list[int]) -> None:
        """Replace validated pool tag associations in the same transaction."""
        self.connection.execute("DELETE FROM main.resource_pool_tag WHERE pool_id=?", (pool_id,))
        self.connection.executemany(
            "INSERT INTO main.resource_pool_tag(pool_id,tag_id) VALUES(?,?)",
            [(pool_id, tag_id) for tag_id in tag_ids],
        )


class SqliteResourcePoolGateway:
    """Own connection lifetime, writer reservation, and safe storage errors."""

    def __init__(self, db_path: str | None = None, *, access: BusinessAccess) -> None:
        """Retain the configured database path without opening a connection."""
        self.db_path = db_path
        self.access = access

    @contextmanager
    def transaction(self, *, write: bool = False, permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Iterator[SqliteResourcePoolStore]:
        """Commit once or roll back fully, including tags and group membership."""
        try:
            with closing(get_db(self.db_path)) as connection:
                connection.row_factory = sqlite3.Row
                with connection:
                    connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                    with authorized_business_transaction(connection, self.access, permission=permission, project_ids=project_ids):
                        yield SqliteResourcePoolStore(connection)
        except sqlite3.IntegrityError as exc:
            raise ResourcePoolConflictError(
                "The resource-pool change conflicts with an existing reference or constraint."
            ) from exc
        except sqlite3.DatabaseError as exc:
            logger.error("Resource-pool storage operation failed (%s)", type(exc).__name__)
            raise ResourcePoolStorageError(
                "Resource-pool data could not be accessed. Please try again."
            ) from exc
