"""Repository for resource pools, team/function mappings, and project/task assignments."""

from typing import Any, Dict, List, Optional

import pandas as pd

from src.database.connection import get_db
from src.logging_config import get_logger
from src.models.resource_pool import (
    PoolAssignment,
    PoolCapacityDetail,
    PoolMapping,
    ResourcePool,
)

logger = get_logger(__name__)


class ResourcePoolRepository:
    """Encapsulates database operations for Resource Pools, Mappings, and Assignments."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initializes the ResourcePoolRepository.

        Args:
            db_path: Optional path to SQLite database. If None, uses default.
        """
        self.db_path = db_path

    # =========================================================================
    # 1. RESOURCE POOLS
    # =========================================================================
    def get_all_pools(self) -> pd.DataFrame:
        """Retrieves all resource pools ordered by name.

        Returns:
            pd.DataFrame: Table of resource pools.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT id, name, description, capacity_fte, created_at
                FROM resource_pool
                ORDER BY name ASC
                """,
                conn,
            )

    def get_all_resource_pools(self) -> pd.DataFrame:
        """Retrieves all resource pools (alias for get_all_pools).

        Returns:
            pd.DataFrame: Table of resource pools.
        """
        return self.get_all_pools()

    def get_pool_capacity_detail(self, pool_id: int) -> PoolCapacityDetail:
        """Convenience method to compute capacity breakdown and daily overassignments.

        Args:
            pool_id: Resource pool ID.

        Returns:
            PoolCapacityDetail: Detailed capacity calculation.
        """
        from src.repositories.milestone_repo import MilestoneRepository
        from src.repositories.organization_repo import OrganizationRepository
        from src.services.resource_pool_service import ResourcePoolService

        org_repo = OrganizationRepository(self.db_path)
        milestone_repo = MilestoneRepository(self.db_path)
        return ResourcePoolService.calculate_pool_capacity(pool_id, org_repo, self, milestone_repo)

    def get_pool_by_id(self, pool_id: int) -> Optional[ResourcePool]:
        """Retrieves a single resource pool by primary key ID.

        Args:
            pool_id: Resource pool ID.

        Returns:
            Optional[ResourcePool]: ResourcePool instance if found, else None.
        """
        with get_db(self.db_path) as conn:
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
        """Creates a new resource pool record.

        Args:
            pool: ResourcePool instance.

        Returns:
            int: Newly created resource_pool id.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO resource_pool (name, description, capacity_fte)
                VALUES (?, ?, ?)
                """,
                (pool.name.strip(), pool.description.strip(), pool.capacity_fte),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_pool(self, pool: ResourcePool) -> bool:
        """Updates an existing resource pool record.

        Args:
            pool: ResourcePool instance with valid id.

        Returns:
            bool: True if record was updated, False otherwise.
        """
        if pool.id is None:
            return False
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE resource_pool
                SET name = ?, description = ?, capacity_fte = ?
                WHERE id = ?
                """,
                (pool.name.strip(), pool.description.strip(), pool.capacity_fte, pool.id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_pool(self, pool_id: int) -> bool:
        """Deletes a resource pool by ID (cascades mappings and assignments).

        Args:
            pool_id: ID of the resource pool to delete.

        Returns:
            bool: True if deleted, False otherwise.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM resource_pool WHERE id = ?", (pool_id,))
            conn.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # 2. POOL MAPPINGS (TEAMS & FUNCTIONS)
    # =========================================================================
    def get_mappings_by_pool(self, pool_id: int) -> pd.DataFrame:
        """Retrieves all team and function mappings for a given resource pool.

        Args:
            pool_id: Resource pool ID.

        Returns:
            pd.DataFrame: Table of mappings.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT id, pool_id, target_type, target_id, allocation_pct
                FROM resource_pool_mapping
                WHERE pool_id = ?
                ORDER BY target_type ASC, target_id ASC
                """,
                conn,
                params=(pool_id,),
            )

    def get_all_mappings(self) -> pd.DataFrame:
        """Retrieves all resource pool mappings across the portfolio.

        Returns:
            pd.DataFrame: Table of all mappings.
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                """
                SELECT id, pool_id, target_type, target_id, allocation_pct
                FROM resource_pool_mapping
                ORDER BY pool_id ASC, target_type ASC
                """,
                conn,
            )

    def create_mapping(self, mapping: PoolMapping) -> int:
        """Creates or replaces a team/function mapping to a resource pool.

        Args:
            mapping: PoolMapping instance.

        Returns:
            int: Newly created or updated mapping ID.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO resource_pool_mapping (pool_id, target_type, target_id, allocation_pct)
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
            conn.commit()
            return int(cursor.lastrowid)

    def update_mapping(self, mapping_id: int, allocation_pct: float) -> bool:
        """Updates the allocation percentage for an existing mapping.

        Args:
            mapping_id: Primary key mapping ID.
            allocation_pct: New allocation percentage (0.0 to 100.0).

        Returns:
            bool: True if updated.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE resource_pool_mapping
                SET allocation_pct = ?
                WHERE id = ?
                """,
                (float(allocation_pct), mapping_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_mapping(self, mapping_id: int) -> bool:
        """Deletes a pool mapping by ID.

        Args:
            mapping_id: Primary key ID to delete.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM resource_pool_mapping WHERE id = ?", (mapping_id,))
            conn.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # 3. POOL ASSIGNMENTS (PROJECT / TASK WITH FTE & DATES)
    # =========================================================================
    def get_assignments(
        self,
        pool_id: Optional[int] = None,
        project_id: Optional[int] = None,
        task_id: Optional[int] = None,
        only_project_level: bool = False,
    ) -> pd.DataFrame:
        """Retrieves resource pool assignments with optional filters.

        Args:
            pool_id: Filter by resource pool ID.
            project_id: Filter by project ID.
            task_id: Filter by project task ID.
            only_project_level: If True, retrieves only project-level assignments (task_id IS NULL).

        Returns:
            pd.DataFrame: Table of assignments with joined project and task metadata.
        """
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
        params: List[Any] = []
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

        with get_db(self.db_path) as conn:
            return pd.read_sql(query, conn, params=params if params else None)

    def get_assignment_by_id(self, assignment_id: int) -> Optional[PoolAssignment]:
        """Retrieves a single assignment by primary key ID.

        Args:
            assignment_id: Assignment ID.

        Returns:
            Optional[PoolAssignment]: Assignment instance if found, else None.
        """
        with get_db(self.db_path) as conn:
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
        """Creates a new pool assignment to a project or task.

        Args:
            assignment: PoolAssignment instance.

        Returns:
            int: Newly created assignment ID.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO resource_pool_assignment (pool_id, project_id, task_id, fte_assigned, start_date, end_date, notes)
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
            conn.commit()
            return int(cursor.lastrowid)

    def update_assignment(self, assignment: PoolAssignment) -> bool:
        """Updates an existing pool assignment record.

        Args:
            assignment: PoolAssignment instance with valid ID.

        Returns:
            bool: True if updated.
        """
        if assignment.id is None:
            return False
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE resource_pool_assignment
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
            conn.commit()
            return cursor.rowcount > 0

    def delete_assignment(self, assignment_id: int) -> bool:
        """Deletes a pool assignment by ID.

        Args:
            assignment_id: Primary key ID to delete.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM resource_pool_assignment WHERE id = ?", (assignment_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_task_assignments_map(self, task_ids: List[int]) -> dict[int, List[dict[str, Any]]]:
        """Retrieves pool assignments grouped by task_id in a single query.

        Args:
            task_ids: List of project task IDs.

        Returns:
            dict[int, List[dict[str, Any]]]: Map of task_id to list of assignment details.
        """
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
        result: dict[int, List[dict[str, Any]]] = {}
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, task_ids)
            for row in cursor.fetchall():
                tid = int(row[3])
                result.setdefault(tid, []).append({
                    "id": int(row[0]),
                    "pool_id": int(row[1]),
                    "pool_name": str(row[2]),
                    "fte": float(row[4]),
                    "start_date": row[5],
                    "end_date": row[6],
                })
        return result

    def get_project_assignments_map(self, project_ids: List[int]) -> dict[int, List[dict[str, Any]]]:
        """Retrieves project-level pool assignments grouped by project_id in a single query.

        Args:
            project_ids: List of project IDs.

        Returns:
            dict[int, List[dict[str, Any]]]: Map of project_id to list of assignment details.
        """
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
        result: dict[int, List[dict[str, Any]]] = {}
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, project_ids)
            for row in cursor.fetchall():
                pid = int(row[3])
                result.setdefault(pid, []).append({
                    "id": int(row[0]),
                    "pool_id": int(row[1]),
                    "pool_name": str(row[2]),
                    "fte": float(row[4]),
                    "start_date": row[5],
                    "end_date": row[6],
                })
        return result

    # =========================================================================
    # 4. TEAM FUNCTIONS
    # =========================================================================
    def get_team_functions(self, team_id: int) -> List[int]:
        """Retrieves all function IDs assigned to a team.

        Args:
            team_id: Team ID.

        Returns:
            List[int]: List of function IDs.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT function_id
                FROM team_function
                WHERE team_id = ?
                ORDER BY function_id ASC
                """,
                (team_id,),
            )
            return [row[0] for row in cursor.fetchall()]

    def set_team_functions(self, team_id: int, function_ids: List[int]) -> None:
        """Sets the exact list of functions associated with a team.

        Args:
            team_id: Team ID.
            function_ids: List of unique function IDs.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM team_function WHERE team_id = ?", (team_id,))
            unique_ids = sorted(list(set(function_ids)))
            for fid in unique_ids:
                cursor.execute(
                    "INSERT OR IGNORE INTO team_function (team_id, function_id) VALUES (?, ?)",
                    (team_id, fid),
                )
            conn.commit()

    def add_team_function(self, team_id: int, function_id: int) -> bool:
        """Adds a single function to a team.

        Args:
            team_id: Team ID.
            function_id: Function ID.

        Returns:
            bool: True if inserted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO team_function (team_id, function_id) VALUES (?, ?)",
                (team_id, function_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def remove_team_function(self, team_id: int, function_id: int) -> bool:
        """Removes a function from a team.

        Args:
            team_id: Team ID.
            function_id: Function ID.

        Returns:
            bool: True if removed.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM team_function WHERE team_id = ? AND function_id = ?",
                (team_id, function_id),
            )
            conn.commit()
            return cursor.rowcount > 0
