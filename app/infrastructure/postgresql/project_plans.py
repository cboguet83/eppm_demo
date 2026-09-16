"""Actor-scoped relational plan storage and transactional active selection."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from app.application.exceptions import PlanningStorageError
from app.application.ports.planning import TaskChoice
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, Permission
from app.domain.planning.plans import ComparisonTask, PlanContent, ProjectPlan, PlanTask
from app.domain.resources.hierarchy import PoolHierarchy
from app.infrastructure.postgresql.access import PostgresAccessStore
from app.infrastructure.postgresql.authorization import ServerRequestSigner
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.plan_content import capture_content, capture_contents
from app.infrastructure.postgresql.plan_rows import copy_protected_links, read_plans, write_plan
from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolStore
from app.shared.logging import get_logger

logger = get_logger(__name__)


class PostgresPlanStore:
    """Storage within one transaction; public use cases own all lifecycle rules."""

    def __init__(self, connection: psycopg.Connection, access: BusinessAccess,
                 security: PostgresAccessStore) -> None:
        self.connection, self.access, self.security = connection, access, security
        self._visibility: tuple[set[int], set[int]] | None = None

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

    def current_plan_names(self, project_ids: list[int]) -> dict[int, str]:
        """Read active labels in one query under project row security."""
        return dict(self.connection.execute('''SELECT project_id,name FROM eppm.project_plan
            WHERE is_current AND project_id=ANY(%s::bigint[])''', (project_ids,)))

    def list_plans(self, project_id: int) -> list[ProjectPlan]:
        """Read explicit plan contents and metadata under project row security."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            rows = list(cursor.execute('''
                SELECT p.id,p.project_id,p.version,p.name,s.code AS status,p.source_plan_id,
                    p.is_current,p.is_baseline,p.revision,p.author,p.created_at,p.is_frozen
                FROM eppm.project_plan p JOIN eppm.plan_status s ON s.id=p.status_id
                WHERE p.project_id=%s ORDER BY p.version DESC''', (project_id,)))
        contents = read_plans(self.connection, [row['id'] for row in rows])
        visibility = self._endpoint_visibility()
        result = []
        for row in rows:
            content = contents[row['id']]
            content.dependencies = [dep for dep in content.dependencies if self._dependency_visible(dep, content, visibility)]
            result.append(ProjectPlan(**dict(row, content=content)))
        return result

    def _endpoint_visibility(self) -> tuple[set[int], set[int]]:
        if self._visibility is None:
            self._visibility = ({row[0] for row in self.connection.execute('SELECT id FROM eppm.project')},
                                {row[0] for row in self.connection.execute('SELECT coalesce(stable_task_id,id) FROM eppm.project_task')})
        return self._visibility

    @staticmethod
    def _dependency_visible(dependency: dict, content: PlanContent,
                            visibility: tuple[set[int], set[int]]) -> bool:
        projects, tasks = visibility
        if dependency['predecessor_project_id'] is not None:
            return dependency['predecessor_project_id'] in projects
        return dependency['predecessor_task_id'] in tasks | {row['id'] for row in content.tasks}

    def snapshot(self, project_id: int) -> PlanContent:
        return capture_content(self.connection, project_id)

    def baseline_tasks(self, project_ids: list[int]) -> dict[int, list[PlanTask]]:
        """Batch-load baseline tasks under project RLS without returning dependencies."""
        owners = dict(self.connection.execute('SELECT project_id,id FROM eppm.project_plan WHERE is_baseline AND project_id=ANY(%s::bigint[])', (project_ids,)))
        contents = read_plans(self.connection, list(owners.values()))
        active = dict(self.connection.execute('SELECT coalesce(stable_task_id,id),id FROM eppm.current_project_task WHERE project_id=ANY(%s::bigint[])', (project_ids,)))
        return {project: [dict(task, id=active.get(task['id'], -task['id'])) for task in contents[plan].tasks] for project, plan in owners.items()}

    def baseline_projects(self) -> list[int]:
        """Read baseline presence under project RLS without loading snapshot content."""
        return [row[0] for row in self.connection.execute(
            'SELECT project_id FROM eppm.project_plan WHERE is_baseline ORDER BY project_id')]

    def comparison_tasks(self, plan: ProjectPlan) -> list[ComparisonTask]:
        """Align an alternative to active physical row IDs using stable identities."""
        active = dict(self.connection.execute('''SELECT coalesce(stable_task_id,id),id
            FROM eppm.current_project_task WHERE project_id=%s''', (plan.project_id,)))
        return [ComparisonTask(**dict(task, id=active.get(task['id'], -task['id']), stable_id=task['id']))
                for task in plan.content.tasks]

    def comparison_endpoints(self, task_ids: list[int]) -> dict[int, dict]:
        """Resolve visible external stable identities to active chart endpoints."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return {row['stable_id']: dict(row) for row in cursor.execute('''
                SELECT coalesce(stable_task_id,id) AS stable_id,id,project_id,task_name,
                    start_date::text,end_date::text FROM eppm.current_project_task
                WHERE coalesce(stable_task_id,id)=ANY(%s::bigint[])''', (task_ids,))}

    def reschedule_task(self, plan: ProjectPlan, task: PlanTask) -> None:
        """Persist one validated scenario edit and increment its conflict token."""
        self.connection.execute('''UPDATE eppm.project_task SET start_date=%s,end_date=%s
            WHERE project_plan_id=%s AND coalesce(stable_task_id,id)=%s AND NOT is_deleted''',
            (task['start_date'], task['end_date'], plan.id, task['id']))
        self.connection.execute('UPDATE eppm.project_plan SET revision=revision+1 WHERE id=%s', (plan.id,))
        old = next(row for row in plan.content.tasks if row['id'] == task['id'])
        self._event(plan.project_id, plan.id, 'task_dates',
                    f"{task['id']}:{old['start_date']}:{old['end_date']}",
                    f"{task['id']}:{task['start_date']}:{task['end_date']}")

    def update_content(self, plan: ProjectPlan, content: PlanContent) -> None:
        """Persist a validated alternative revision without touching active rows."""
        write_plan(self.connection, plan.id, plan.project_id, content, previous=plan.content)
        self.connection.execute('UPDATE eppm.project_plan SET revision=revision+1 WHERE id=%s', (plan.id,))
        self._event(plan.project_id, plan.id, 'content', str(plan.revision), str(plan.revision + 1))

    def tag_choices(self) -> dict[int, str]:
        return dict(self.connection.execute('SELECT id,tag FROM eppm.tag_dictionnary ORDER BY tag,id'))

    def task_choices(self) -> list[TaskChoice]:
        """Batch active selector labels while keeping physical version IDs private."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return [TaskChoice(**row) for row in cursor.execute('''
                SELECT coalesce(t.stable_task_id,t.id) AS id,t.task_name,t.project_id,p.name AS project_name
                FROM eppm.current_project_task t JOIN eppm.project p ON p.id=t.project_id
                ORDER BY t.project_id,t.start_date,t.id''')]

    def versioned_projects(self) -> list[int]:
        """Read current-plan owners without loading their schedule snapshots."""
        return [row[0] for row in self.connection.execute('SELECT project_id FROM eppm.project_plan WHERE is_current')]

    def current_context(self, project_ids: list[int], task_ids: list[int]) -> dict[int, PlanContent]:
        """Resolve live schedules in scoped batches, including tasks edited through menus."""
        owners = [row[0] for row in self.connection.execute('''
            SELECT project_id FROM eppm.project_plan WHERE is_current AND
            (project_id=ANY(%s::bigint[]) OR project_id IN
                (SELECT project_id FROM eppm.project_task WHERE coalesce(stable_task_id,id)=ANY(%s::bigint[])))''', (project_ids, task_ids))]
        result = capture_contents(self.connection, owners)
        visibility = self._endpoint_visibility()
        for content in result.values():
            content.dependencies = [dep for dep in content.dependencies if self._dependency_visible(dep, content, visibility)]
        return result

    def validate_references(self, project_id: int, content: PlanContent) -> None:
        """Check pool leaves, endpoint ownership and visible catalog references."""
        tree = PoolHierarchy(PostgresResourcePoolStore(self.connection).get_all_pools())
        for assignment in content.assignments:
            tree.require_leaf(assignment.pool_id)
        known = {task['id'] for plan in self.list_plans(project_id) for task in plan.content.tasks}
        known.update(row[0] for row in self.connection.execute(
            'SELECT coalesce(stable_task_id,id) FROM eppm.project_task WHERE project_id=%s', (project_id,)))
        if any(task['id'] > 0 and task['id'] not in known for task in content.tasks):
            raise ValueError('A task identity does not belong to this project.')
        internal = {task['id'] for task in content.tasks}
        for dep in content.dependencies:
            predecessor = dep['predecessor_task_id']
            if predecessor is not None and predecessor not in internal and predecessor not in known:
                if predecessor not in self._endpoint_visibility()[1]:
                    raise ValueError('A predecessor task is unavailable in the current project plans.')
            predecessor_project = dep['predecessor_project_id']
            if predecessor_project is not None and not self.connection.execute(
                    'SELECT id FROM eppm.project WHERE id=%s', (predecessor_project,)).fetchone():
                raise AccessDenied()
        tag_ids = {tag['tag_id'] for tags in content.task_tags.values() for tag in tags if tag['tag_id'] is not None}
        available = {row[0] for row in self.connection.execute(
            'SELECT id FROM eppm.tag_dictionnary WHERE id=ANY(%s::bigint[])', (list(tag_ids),))}
        if available != tag_ids:
            raise ValueError('A task tag no longer exists.')
        known_assignments = {row.id for plan in self.list_plans(project_id) for row in plan.content.assignments}
        known_assignments.update(row[0] for row in self.connection.execute(
            'SELECT id FROM eppm.resource_pool_assignment WHERE project_id=%s', (project_id,)))
        identities = [row.id for row in content.assignments if row.id and row.id > 0]
        if len(identities) != len(set(identities)) or set(identities) - known_assignments:
            raise ValueError('An assignment identity is duplicated or belongs to another project.')

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
            (project_id,version,name,status_id,source_plan_id,is_current,author,created_at)
            SELECT %s,coalesce(max(version),0)+1,%s,(SELECT id FROM eppm.plan_status WHERE code=%s),
                %s,%s,%s,%s FROM eppm.project_plan WHERE project_id=%s RETURNING id''',
            (project_id, name, status, source, current, self.access.audit_actor,
             datetime.fromtimestamp(self.access.policy.clock(), timezone.utc), project_id)).fetchone()[0]
        write_plan(self.connection, identity, project_id, content)
        if source is not None:
            copy_protected_links(self.connection, source, identity)
        self._event(project_id, identity, 'created', None, status)
        return next(row for row in self.list_plans(project_id) if row.id == identity)

    def metadata(self, plan: ProjectPlan, action: str, value: str) -> None:
        """Persist an already-authorized metadata change and its immutable audit record."""
        if action == 'status':
            if value == 'deleted':
                self.connection.execute('UPDATE eppm.project_plan SET is_current=false,is_baseline=false WHERE id=%s', (plan.id,))
                for designation in ('current', 'baseline'):
                    if getattr(plan, 'is_' + designation):
                        self._event(plan.project_id, plan.id, designation, 'true', 'false')
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
            if action == 'baseline' and value == 'true':
                self.connection.execute('UPDATE eppm.project_plan SET is_frozen=true WHERE id=%s', (plan.id,))
        self.connection.execute('UPDATE eppm.project_cache_revision SET revision=revision+1 WHERE project_id=%s', (plan.project_id,))
        self._event(plan.project_id, plan.id, action, old, value)


class PostgresPlanGateway:
    """Keep plan rows, metadata and activation in one actor-bound transaction."""

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
        except (psycopg.errors.ForeignKeyViolation, psycopg.errors.RestrictViolation):
            raise ValueError('The plan change conflicts with protected references in other projects or a removed resource.') from None
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Plan storage failure (%s; SQLSTATE=%s)', type(error).__name__, getattr(error, 'sqlstate', None))
            raise PlanningStorageError('The plan could not be saved. Reload and try again.') from None
