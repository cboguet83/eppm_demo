"""Native pool catalogs, recursive memberships and scoped resource assignments."""

from collections.abc import Callable, Collection, Sequence
from datetime import date

import psycopg
from psycopg.rows import dict_row

from app.application.exceptions import ResourcePoolConflictError, ResourcePoolStorageError
from app.application.ports.resource_pools import ResourcePoolStore
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Permission
from app.domain.hierarchy import HierarchyType
from app.domain.resources.models import (
    AssignmentLink, AssignmentRow, PoolAssignment, PoolCapacityException, PoolGroupMemberRow, PoolMapping,
    PoolTag, PoolTagChoice, ResourcePool, ResourcePoolGroup, ResourcePoolGroupMember,
)
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.hierarchy import hierarchy_types
from app.infrastructure.postgresql.pool import Database
from app.shared.logging import get_logger

logger = get_logger(__name__)
_CREATED = "to_char(created_at AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') AS created_at"
_POOL = f"id,name,COALESCE(description,'') AS description,capacity_fte,{_CREATED},hierarchy_type_id"
_GROUP = f"id,name,COALESCE(description,'') AS description,{_CREATED},hierarchy_type_id"


def _assignment_values(assignment: PoolAssignment) -> tuple[object, ...]:
    """Bind nonmonetary FTE and native dates while retaining absent date endpoints."""
    return (assignment.pool_id, assignment.project_id, assignment.task_id, assignment.fte_assigned,
            date.fromisoformat(assignment.start_date) if assignment.start_date is not None else None,
            date.fromisoformat(assignment.end_date) if assignment.end_date is not None else None, assignment.notes,
            assignment.schedule_anchor, assignment.offset_days, assignment.duration_days)


class PostgresResourcePoolStore:
    """Keep catalog, tag, group and assignment operations on the caller's snapshot."""

    def __init__(self, connection: psycopg.Connection) -> None:
        """Retain the connection without owning its transaction or lifetime."""
        self.connection = connection

    def _rows[Record](self, model: Callable[..., Record], source: str,
                      parameters: Sequence[object] = ()) -> list[Record]:
        """Adapt explicit SQL columns at the dynamic driver-to-record boundary."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return [model(**row) for row in cursor.execute(source, parameters)]

    def get_all_hierarchy_types(self) -> list[HierarchyType]:
        """Read stable hierarchy codes and translated labels in one query."""
        return hierarchy_types(self.connection)

    def capacity_exceptions(self, pool_ids: list[int]) -> list[PoolCapacityException]:
        """Read requested pool reductions in a single authorized query."""
        return self._rows(PoolCapacityException, '''SELECT id,pool_id,to_char(start_date,'YYYY-MM-DD') AS start_date,
            to_char(end_date,'YYYY-MM-DD') AS end_date,reduction_fte::double precision AS reduction_fte,reason
            FROM eppm.resource_pool_capacity_exception WHERE pool_id=ANY(%s::bigint[]) ORDER BY start_date,id''', (pool_ids,))

    def save_capacity_exception(self, item: PoolCapacityException) -> int:
        """Create or edit an absolute reduction under the shared-management guard."""
        values = (item.pool_id, date.fromisoformat(item.start_date), date.fromisoformat(item.end_date), item.reduction_fte, item.reason)
        if item.id is None:
            return self.connection.execute('''INSERT INTO eppm.resource_pool_capacity_exception
                (pool_id,start_date,end_date,reduction_fte,reason) VALUES (%s,%s,%s,%s,%s) RETURNING id''', values).fetchone()[0]
        row = self.connection.execute('''UPDATE eppm.resource_pool_capacity_exception SET pool_id=%s,start_date=%s,
            end_date=%s,reduction_fte=%s,reason=%s WHERE id=%s RETURNING id''', (*values, item.id)).fetchone()
        if row is None:
            raise ValueError('The capacity exception no longer exists.')
        return row[0]

    def delete_capacity_exception(self, identity: int) -> bool:
        """Delete one pool reduction without changing nominal capacity."""
        return self.connection.execute('DELETE FROM eppm.resource_pool_capacity_exception WHERE id=%s', (identity,)).rowcount > 0

    def get_all_pools(self) -> list[ResourcePool]:
        """Read the shared pool catalog in stable name order."""
        return self._rows(ResourcePool, f'SELECT {_POOL} FROM eppm.resource_pool ORDER BY name COLLATE "C",id')

    def get_pool_by_id(self, pool_id: int) -> ResourcePool | None:
        """Read one pool, including optional capacity and hierarchy classification."""
        rows = self._rows(ResourcePool, f'SELECT {_POOL} FROM eppm.resource_pool WHERE id=%s', (pool_id,))
        return rows[0] if rows else None

    def create_pool(self, pool: ResourcePool) -> int:
        """Create normalized pool details within the enclosing compound save."""
        return self.connection.execute('INSERT INTO eppm.resource_pool(name,description,capacity_fte,hierarchy_type_id) '
                                       'VALUES (%s,%s,%s,%s) RETURNING id',
                                       (pool.name, pool.description, pool.capacity_fte, pool.hierarchy_type_id)).fetchone()[0]

    def update_pool(self, pool: ResourcePool) -> bool:
        """Preserve identity and creation time when updating pool details."""
        return self.connection.execute('UPDATE eppm.resource_pool SET name=%s,description=%s,capacity_fte=%s,hierarchy_type_id=%s WHERE id=%s',
                                       (pool.name, pool.description, pool.capacity_fte, pool.hierarchy_type_id, pool.id)).rowcount > 0

    def delete_pool(self, pool_id: int) -> bool:
        """Delete the pool and its native cascading memberships, tags and demand."""
        return self.connection.execute('DELETE FROM eppm.resource_pool WHERE id=%s', (pool_id,)).rowcount > 0

    def get_all_group_members(self) -> list[ResourcePoolGroupMember]:
        """Read graph identities once, without per-group connection acquisition."""
        return self._rows(ResourcePoolGroupMember, 'SELECT group_id,pool_id,child_group_id FROM eppm.resource_pool_group_member ORDER BY id')

    def groups(self) -> list[ResourcePoolGroup]:
        """Read group details in the same snapshot used for recursive counts."""
        return self._rows(ResourcePoolGroup, f'SELECT {_GROUP} FROM eppm.resource_pool_group ORDER BY name COLLATE "C",id')

    def get_pool_group_by_id(self, group_id: int) -> ResourcePoolGroup | None:
        """Read one group without materializing its recursive graph."""
        rows = self._rows(ResourcePoolGroup, f'SELECT {_GROUP} FROM eppm.resource_pool_group WHERE id=%s', (group_id,))
        return rows[0] if rows else None

    def create_pool_group(self, group: ResourcePoolGroup) -> int:
        """Create group details before adding validated membership in the same save."""
        return self.connection.execute('INSERT INTO eppm.resource_pool_group(name,description,hierarchy_type_id) VALUES (%s,%s,%s) RETURNING id',
                                       (group.name, group.description, group.hierarchy_type_id)).fetchone()[0]

    def update_pool_group(self, group: ResourcePoolGroup) -> bool:
        """Update group details without changing identity or creation time."""
        return self.connection.execute('UPDATE eppm.resource_pool_group SET name=%s,description=%s,hierarchy_type_id=%s WHERE id=%s',
                                       (group.name, group.description, group.hierarchy_type_id, group.id)).rowcount > 0

    def delete_pool_group(self, group_id: int) -> bool:
        """Delete group membership edges while preserving child groups and pools."""
        return self.connection.execute('DELETE FROM eppm.resource_pool_group WHERE id=%s', (group_id,)).rowcount > 0

    def get_group_members(self, group_id: int) -> list[PoolGroupMemberRow]:
        """Join direct member labels with stable group-before-pool ordering."""
        return self._rows(PoolGroupMemberRow, '''SELECT gm.id,gm.group_id,gm.pool_id,gm.child_group_id,
            CASE WHEN gm.pool_id IS NOT NULL THEN 'pool' ELSE 'group' END AS member_type,
            COALESCE(p.name,g.name) AS member_name FROM eppm.resource_pool_group_member gm
            LEFT JOIN eppm.resource_pool p ON p.id=gm.pool_id LEFT JOIN eppm.resource_pool_group g ON g.id=gm.child_group_id
            WHERE gm.group_id=%s ORDER BY (CASE WHEN gm.pool_id IS NOT NULL THEN 'pool' ELSE 'group' END) COLLATE "C",
            COALESCE(p.name,g.name) COLLATE "C",gm.id''', (group_id,))

    def replace_group_members(self, group_id: int, pool_ids: list[int], child_ids: list[int]) -> None:
        """Replace all validated edges atomically under native cycle protection."""
        self.connection.execute('DELETE FROM eppm.resource_pool_group_member WHERE group_id=%s', (group_id,))
        with self.connection.cursor() as cursor:
            cursor.executemany('INSERT INTO eppm.resource_pool_group_member(group_id,pool_id,child_group_id) VALUES (%s,%s,%s)',
                               [(group_id, pool_id, None) for pool_id in pool_ids] + [(group_id, None, child) for child in child_ids])

    def get_all_mappings(self) -> list[PoolMapping]:
        """Read configuration mappings without joining private employee details."""
        return self._rows(PoolMapping, 'SELECT id,pool_id,target_type,target_id,allocation_pct FROM eppm.resource_pool_mapping '
                                      'ORDER BY pool_id,target_type COLLATE "C",target_id')

    def get_mappings_by_pool(self, pool_id: int) -> list[PoolMapping]:
        """Read one pool's mappings in target-type and identity order."""
        return self._rows(PoolMapping, 'SELECT id,pool_id,target_type,target_id,allocation_pct FROM eppm.resource_pool_mapping '
                                      'WHERE pool_id=%s ORDER BY target_type COLLATE "C",target_id', (pool_id,))

    def create_mapping(self, mapping: PoolMapping) -> int:
        """Upsert one target percentage and return its preserved mapping identity."""
        return self.connection.execute('INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) VALUES (%s,%s,%s,%s) '
                                       'ON CONFLICT(pool_id,target_type,target_id) DO UPDATE SET allocation_pct=excluded.allocation_pct RETURNING id',
                                       (mapping.pool_id, mapping.target_type, mapping.target_id, mapping.allocation_pct)).fetchone()[0]

    def update_mapping(self, mapping_id: int, allocation_pct: float) -> bool:
        """Change a nonmonetary capacity percentage without changing its target."""
        return self.connection.execute('UPDATE eppm.resource_pool_mapping SET allocation_pct=%s WHERE id=%s', (allocation_pct, mapping_id)).rowcount > 0

    def delete_mapping(self, mapping_id: int) -> bool:
        """Delete one configuration mapping."""
        return self.connection.execute('DELETE FROM eppm.resource_pool_mapping WHERE id=%s', (mapping_id,)).rowcount > 0

    def get_assignments(self, pool_id: int | None = None, project_id: int | None = None, task_id: int | None = None,
                        only_project_level: bool = False, *, pool_ids: Collection[int] | None = None) -> list[AssignmentRow]:
        """Filter actor-visible demand before resolving optional task/date labels."""
        return self._rows(AssignmentRow, '''WITH bounds AS (
            SELECT project_id,min(start_date) AS first,max(end_date) AS last FROM eppm.project_task
            WHERE project_id IN (SELECT project_id FROM eppm.resource_pool_assignment WHERE schedule_anchor IS NOT NULL)
            GROUP BY project_id) SELECT a.id,a.pool_id,pool.name AS pool_name,a.project_id,p.name AS project_name,
            a.task_id,t.task_name,to_char(t.start_date,'YYYY-MM-DD') AS task_start_date,to_char(t.end_date,'YYYY-MM-DD') AS task_end_date,
            a.schedule_anchor,a.offset_days,a.duration_days,a.fte_assigned,to_char(a.start_date,'YYYY-MM-DD') AS custom_start_date,to_char(a.end_date,'YYYY-MM-DD') AS custom_end_date,
            to_char(COALESCE(relative.first,a.start_date,t.start_date),'YYYY-MM-DD') AS effective_start_date,
            to_char(COALESCE(relative.last,a.end_date,t.end_date),'YYYY-MM-DD') AS effective_end_date,a.notes
            FROM eppm.resource_pool_assignment a JOIN eppm.resource_pool pool ON pool.id=a.pool_id
            JOIN eppm.project p ON p.id=a.project_id LEFT JOIN eppm.project_task t ON t.id=a.task_id
            LEFT JOIN bounds b ON b.project_id=a.project_id
            LEFT JOIN LATERAL eppm.assignment_period(coalesce(t.start_date,b.first,current_date),
                coalesce(t.end_date,b.last,current_date),a.schedule_anchor,a.offset_days,a.duration_days) relative ON true
            WHERE (%s::bigint IS NULL OR a.pool_id=%s) AND (%s::bigint IS NULL OR a.project_id=%s)
            AND (CASE WHEN %s THEN a.task_id IS NULL ELSE %s::bigint IS NULL OR a.task_id=%s END)
            AND (%s::bigint[] IS NULL OR a.pool_id=ANY(%s::bigint[])) ORDER BY a.pool_id,a.project_id,a.task_id NULLS FIRST,a.id''',
                          (pool_id, pool_id, project_id, project_id, only_project_level, task_id, task_id,
                           None if pool_ids is None else list(pool_ids), None if pool_ids is None else list(pool_ids)))

    def get_assignment_by_id(self, assignment_id: int) -> PoolAssignment | None:
        """Read one visible assignment with ISO date and empty-note boundaries."""
        rows = self._rows(PoolAssignment, '''SELECT id,pool_id,project_id,task_id,fte_assigned,
            to_char(start_date,'YYYY-MM-DD') AS start_date,to_char(end_date,'YYYY-MM-DD') AS end_date,COALESCE(notes,'') AS notes,schedule_anchor,offset_days,duration_days
            FROM eppm.resource_pool_assignment WHERE id=%s''', (assignment_id,))
        return rows[0] if rows else None

    def create_assignment(self, assignment: PoolAssignment) -> int:
        """Create native demand under project-edit and task-owner guards."""
        return self.connection.execute('INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned,start_date,end_date,notes,schedule_anchor,offset_days,duration_days) '
                                       'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id', _assignment_values(assignment)).fetchone()[0]

    def update_assignment(self, assignment: PoolAssignment) -> bool:
        """Require both original and new project ownership for assignment moves."""
        return self.connection.execute('UPDATE eppm.resource_pool_assignment SET pool_id=%s,project_id=%s,task_id=%s,fte_assigned=%s,start_date=%s,end_date=%s,notes=%s,schedule_anchor=%s,offset_days=%s,duration_days=%s '
                                       'WHERE id=%s', (*_assignment_values(assignment), assignment.id)).rowcount > 0

    def delete_assignment(self, assignment_id: int) -> bool:
        """Delete visible demand only with edit permission on its current owner."""
        return self.connection.execute('DELETE FROM eppm.resource_pool_assignment WHERE id=%s', (assignment_id,)).rowcount > 0

    def _assignment_map(self, ids: list[int], *, tasks: bool) -> dict[int, list[AssignmentLink]]:
        """Batch compact planning links without leaking hidden keys or task demand into projects."""
        if not ids:
            return {}
        owner, extra = ('task_id', '') if tasks else ('project_id', 'AND a.task_id IS NULL')
        result: dict[int, list[AssignmentLink]] = {}
        for identity, pool_id, pool_name, owner_id, fte, start, end in self.connection.execute(
            f'''WITH bounds AS (SELECT project_id,min(start_date) AS first,max(end_date) AS last
                FROM eppm.project_task WHERE project_id IN (SELECT project_id FROM eppm.resource_pool_assignment
                WHERE {owner}=ANY(%s::bigint[])) GROUP BY project_id)
                SELECT a.id,a.pool_id,p.name,a.{owner},a.fte_assigned,
                to_char(coalesce(relative.first,a.start_date),'YYYY-MM-DD'),
                to_char(coalesce(relative.last,a.end_date),'YYYY-MM-DD')
                FROM eppm.resource_pool_assignment a JOIN eppm.resource_pool p ON p.id=a.pool_id
                LEFT JOIN eppm.project_task t ON t.id=a.task_id LEFT JOIN bounds b ON b.project_id=a.project_id
                LEFT JOIN LATERAL eppm.assignment_period(coalesce(t.start_date,b.first,current_date),
                    coalesce(t.end_date,b.last,current_date),a.schedule_anchor,a.offset_days,a.duration_days) relative ON true
                WHERE a.{owner}=ANY(%s::bigint[]) {extra} ORDER BY p.name COLLATE "C",a.id''', (ids, ids)):
            result.setdefault(owner_id, []).append(AssignmentLink(id=identity, pool_id=pool_id, pool_name=pool_name,
                                                                 fte=fte, start_date=start, end_date=end))
        return result

    def get_task_assignments_map(self, task_ids: list[int]) -> dict[int, list[AssignmentLink]]:
        """Read only requested visible task allocations in one query."""
        return self._assignment_map(task_ids, tasks=True)

    def get_project_assignments_map(self, project_ids: list[int]) -> dict[int, list[AssignmentLink]]:
        """Read only requested visible project-level allocations in one query."""
        return self._assignment_map(project_ids, tasks=False)

    def get_tag_choices(self) -> list[PoolTagChoice]:
        """Read dictionary choices with their optional group labels."""
        return self._rows(PoolTagChoice, 'SELECT t.id,t.tag,t.tag_group_id,g.tag_group_name FROM eppm.tag_dictionnary t '
                                        'LEFT JOIN eppm.tag_group g ON g.id=t.tag_group_id ORDER BY t.tag COLLATE "C",t.id')

    def get_pool_tags(self, pool_id: int) -> list[PoolTag]:
        """Read the selected pool's current tags in dictionary display order."""
        return self._rows(PoolTag, 'SELECT p.id,p.pool_id,p.tag_id,t.tag AS tag_name,g.tag_group_name FROM eppm.resource_pool_tag p '
                                  'JOIN eppm.tag_dictionnary t ON t.id=p.tag_id LEFT JOIN eppm.tag_group g ON g.id=t.tag_group_id '
                                  'WHERE p.pool_id=%s ORDER BY t.tag COLLATE "C",p.id', (pool_id,))

    def set_pool_tags(self, pool_id: int, tag_ids: list[int]) -> None:
        """Replace validated tag choices as part of the complete pool save."""
        self.connection.execute('DELETE FROM eppm.resource_pool_tag WHERE pool_id=%s', (pool_id,))
        with self.connection.cursor() as cursor:
            cursor.executemany('INSERT INTO eppm.resource_pool_tag(pool_id,tag_id) VALUES (%s,%s)', [(pool_id, tag) for tag in tag_ids])


class PostgresResourcePoolGateway:
    """Own authorized pool callbacks, complete replay and safe error translation."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the restricted pool, server signing key and current actor policy."""
        self.database, self.key, self.access = database, key, access

    def run[Result](self, operation: Callable[[ResourcePoolStore], Result], *, write: bool = False,
                    permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Result:
        """Run each complete attempt with a new store and current authorization."""
        try:
            return run_business(self.database, self.key, self.access, lambda connection: operation(PostgresResourcePoolStore(connection)),
                                write=write, permission=permission, project_ids=project_ids)
        except psycopg.IntegrityError:
            raise ResourcePoolConflictError('The resource-pool change conflicts with an existing reference or constraint.') from None
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Resource-pool storage operation failed (%s)', type(error).__name__)
            raise ResourcePoolStorageError('Resource-pool data could not be accessed. Please try again.') from None
