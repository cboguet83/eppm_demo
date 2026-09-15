"""Actor-scoped append-only plan storage and transactional current projection."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.application.exceptions import PlanningStorageError
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, Permission
from app.domain.planning.plans import PlanContent, ProjectPlan
from app.domain.resources.hierarchy import PoolHierarchy
from app.infrastructure.postgresql.access import PostgresAccessStore
from app.infrastructure.postgresql.authorization import ServerRequestSigner
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.plan_content import capture_content, decode_content, encode_content
from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolStore


class PostgresPlanStore:
    """Storage within one transaction; public use cases own all lifecycle rules."""

    def __init__(self, connection: psycopg.Connection, access: BusinessAccess,
                 security: PostgresAccessStore) -> None:
        self.connection, self.access, self.security = connection, access, security

    def lock_project(self, project_id: int) -> None:
        """Serialize version numbering and designation changes for one owner."""
        if not self.connection.execute('SELECT id FROM eppm.project WHERE id=%s FOR UPDATE', (project_id,)).fetchone():
            raise AccessDenied()

    def permissions(self, project_id: int) -> tuple[bool, bool, bool]:
        """Resolve editor, approver and business-admin privileges in this snapshot."""
        allowed = []
        for permission in (Permission.EDIT, Permission.APPROVE):
            try:
                self.access.require(self.security, permission, [project_id])
                allowed.append(True)
            except AccessDenied:
                allowed.append(False)
        return (*allowed, self.access.global_permission(self.security, Permission.SHARED))

    def list_plans(self, project_id: int) -> list[ProjectPlan]:
        """Read immutable contents and current metadata under project RLS."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return [ProjectPlan(**dict(row, content=decode_content(row['content']))) for row in cursor.execute('''
                SELECT p.id,p.project_id,p.version,p.name,s.code AS status,p.source_plan_id,
                    p.is_current,p.is_baseline,p.revision,p.author,p.created_at,p.content
                FROM eppm.project_plan p JOIN eppm.plan_status s ON s.id=p.status_id
                WHERE p.project_id=%s ORDER BY p.version DESC''', (project_id,))]

    def snapshot(self, project_id: int) -> PlanContent:
        return capture_content(self.connection, project_id)

    def validate_references(self, project_id: int, content: PlanContent) -> None:
        """Check pool leaves, endpoint ownership and visible catalog references."""
        tree = PoolHierarchy(PostgresResourcePoolStore(self.connection).get_all_pools())
        for assignment in content.assignments:
            tree.require_leaf(assignment.pool_id)
        known = {task['id'] for plan in self.list_plans(project_id) for task in plan.content.tasks}
        known.update(row[0] for row in self.connection.execute(
            'SELECT id FROM eppm.project_task WHERE project_id=%s', (project_id,)))
        if any(task['id'] > 0 and task['id'] not in known for task in content.tasks):
            raise ValueError('A task identity does not belong to this project.')
        internal = {task['id'] for task in content.tasks}
        for dep in content.dependencies:
            predecessor = dep['predecessor_task_id']
            if predecessor is not None and predecessor not in internal:
                if not self.connection.execute('SELECT id FROM eppm.project_task WHERE id=%s', (predecessor,)).fetchone():
                    raise ValueError('A predecessor task is unavailable in the current project plans.')
            predecessor_project = dep['predecessor_project_id']
            if predecessor_project is not None and not self.connection.execute(
                    'SELECT id FROM eppm.project WHERE id=%s', (predecessor_project,)).fetchone():
                raise AccessDenied()
        tag_ids = {tag for tags in content.task_tags.values() for tag in tags}
        available = {row[0] for row in self.connection.execute(
            'SELECT id FROM eppm.tag_dictionnary WHERE id=ANY(%s::bigint[])', (list(tag_ids),))}
        if available != tag_ids:
            raise ValueError('A task tag no longer exists.')

    def reserve_identities(self, content: PlanContent) -> PlanContent:
        """Reserve permanent task/assignment IDs; sequence gaps on rollback are harmless."""
        identities = {row['id']: self.connection.execute(
            "SELECT nextval(pg_get_serial_sequence('eppm.project_task','id'))").fetchone()[0]
            for row in content.tasks if row['id'] < 0}
        tasks = [dict(row, id=identities.get(row['id'], row['id'])) for row in content.tasks]
        dependencies = [dict(row, task_id=identities.get(row['task_id'], row['task_id']),
            predecessor_task_id=identities.get(row['predecessor_task_id'], row['predecessor_task_id']))
            for row in content.dependencies]
        assignments = [replace(row, task_id=identities.get(row.task_id, row.task_id),
            id=row.id if row.id and row.id > 0 else self.connection.execute(
                "SELECT nextval(pg_get_serial_sequence('eppm.resource_pool_assignment','id'))").fetchone()[0])
            for row in content.assignments]
        return PlanContent(tasks, dependencies, assignments,
            {identities.get(identity, identity): tags for identity, tags in content.task_tags.items()})

    def _event(self, project_id: int, plan_id: int, action: str,
               old: str | None, new: str | None) -> None:
        self.connection.execute('''INSERT INTO eppm.project_plan_event
            (project_id,plan_id,action,old_value,new_value,author,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)''',
            (project_id, plan_id, action, old, new, self.access.audit_actor,
             datetime.fromtimestamp(self.access.policy.clock(), timezone.utc)))

    def insert(self, project_id: int, name: str, status: str, source: int | None,
               content: PlanContent, *, current: bool = False) -> ProjectPlan:
        """Append a complete snapshot with a project-local monotonically increasing version."""
        identity = self.connection.execute('''INSERT INTO eppm.project_plan
            (project_id,version,name,status_id,source_plan_id,is_current,author,created_at,content)
            SELECT %s,coalesce(max(version),0)+1,%s,(SELECT id FROM eppm.plan_status WHERE code=%s),
                %s,%s,%s,%s,%s FROM eppm.project_plan WHERE project_id=%s RETURNING id''',
            (project_id, name, status, source, current, self.access.audit_actor,
             datetime.fromtimestamp(self.access.policy.clock(), timezone.utc), Jsonb(encode_content(content)), project_id)).fetchone()[0]
        self._event(project_id, identity, 'created', None, status)
        return next(row for row in self.list_plans(project_id) if row.id == identity)

    def metadata(self, plan: ProjectPlan, action: str, value: str) -> None:
        """Persist an already-authorized metadata change and its immutable audit record."""
        if action == 'status':
            self.connection.execute('''UPDATE eppm.project_plan SET status_id=(SELECT id FROM eppm.plan_status
                WHERE code=%s),revision=revision+1 WHERE id=%s''', (value, plan.id))
            old = plan.status
        else:
            column = 'is_current' if action == 'current' else 'is_baseline'
            old = str(getattr(plan, column)).lower()
            if value == 'true':
                previous = self.connection.execute(
                    f'UPDATE eppm.project_plan SET {column}=false,revision=revision+1 '
                    f'WHERE project_id=%s AND {column} AND id<>%s RETURNING id', (plan.project_id, plan.id)).fetchall()
                for identity, in previous:
                    self._event(plan.project_id, identity, action, 'true', 'false')
            self.connection.execute(f'UPDATE eppm.project_plan SET {column}=%s,revision=revision+1 WHERE id=%s',
                                    (value == 'true', plan.id))
        self._event(plan.project_id, plan.id, action, old, value)

    def publish(self, plan: ProjectPlan) -> None:
        """Materialize the designated immutable plan for existing current-only readers."""
        from app.infrastructure.postgresql.plan_projection import publish_current
        publish_current(self.connection, plan.project_id, plan.content)


class PostgresPlanGateway:
    """Keep plan snapshots, metadata and projection writes in one actor-bound transaction."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        self.database, self.key, self.access = database, key, access

    def run[T](self, operation: Callable[[PostgresPlanStore], T], *, write: bool = False) -> T:
        """Translate storage failures after rollback without leaking SQL or credentials."""
        def callback(connection: psycopg.Connection) -> T:
            security = PostgresAccessStore(connection, ServerRequestSigner(self.key), self.access.policy,
                                           self.access.actor, writable=write)
            return operation(PostgresPlanStore(connection, self.access, security))
        try:
            return run_business(self.database, self.key, self.access, callback, write=write)
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError):
            raise PlanningStorageError('The plan could not be saved. Reload and try again.') from None
