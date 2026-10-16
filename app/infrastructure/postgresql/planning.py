"""Native task scheduling, scoped dependency graphs and complete planning saves."""

from collections.abc import Callable, Collection, Sequence
from datetime import date
from typing import cast

import psycopg
from psycopg.rows import dict_row

from app.application.exceptions import PlanningConflictError, PlanningStorageError
from app.application.ports.planning import (
    ExternalTask, PlanningStore, PlanningTaskBundle, PlanningTotals, ProjectSummary, TaskChoice, TaskRow,
)
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Permission
from app.domain.planning.records import DependencyInput, DependencySchedule, ProjectBounds, TaskInput, TaskValues
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.derived_cache import CacheRecord, DerivedCacheState, PostgresDerivedCache
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.planning_summaries import read_project_summaries
from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolStore
from app.infrastructure.postgresql.tags import PostgresTagStore
from app.domain.planning.project_dependencies import ProjectDependency, ProjectDependencyInput
from app.infrastructure.postgresql.project_dependencies import (
    read_project_dependencies, project_dependency_revision, write_project_dependencies,
)
from app.shared.logging import get_logger
from app.infrastructure.postgresql.plan_guards import require_current_edit, require_reschedule

logger = get_logger(__name__)
_TASK_COLUMNS = """m.id,m.project_id,m.task_name,m.phase,to_char(m.start_date,'YYYY-MM-DD') AS start_date,
                   to_char(m.end_date,'YYYY-MM-DD') AS end_date,m.progress_pct,m.description,m.predecessor_id"""
_INSERT_TASK = '''INSERT INTO eppm.project_task(project_plan_id,project_id,task_name,phase,start_date,end_date,progress_pct,description,predecessor_id)
                  VALUES ((SELECT id FROM eppm.project_plan WHERE project_id=%s AND is_current),%s,%s,%s,%s,%s,%s,%s,%s)'''
_INSERT_DEPENDENCY = '''INSERT INTO eppm.current_task_dependencies(task_id,predecessor_task_id,predecessor_project_id,link_type,lag_days)
                        VALUES (%s,%s,%s,%s,%s)'''


def _task_params(values: TaskValues) -> tuple[object, ...]:
    """Bind normalized dates natively while retaining optional field defaults."""
    return (values['task_name'], values.get('phase', 'General'), date.fromisoformat(values['start_date']),
            date.fromisoformat(values['end_date']), values.get('progress_pct', 0), values.get('description', ''), values.get('predecessor_id'))


def _dependency_params(task_id: int, dependency: DependencyInput) -> tuple[object, ...]:
    """Bind normalized endpoints and settings without changing the submitted link."""
    return (task_id, dependency.get('predecessor_task_id'), dependency.get('predecessor_project_id'),
            dependency['link_type'], dependency['lag_days'])


class PostgresPlanningStore:
    """Read and mutate schedules using one caller-owned authorized connection."""

    def __init__(self, connection: psycopg.Connection) -> None:
        """Retain the connection without owning its transaction or lifetime."""
        self.connection = connection

    def read_project_dependencies(self, project_ids: list[int]) -> list[ProjectDependency]:
        """Read project-owned incoming links under the current scope."""
        return read_project_dependencies(self.connection, project_ids)

    def project_dependency_revision(self, project_id: int) -> str:
        """Read a scoped revision for conflict-safe link editing."""
        return project_dependency_revision(self.connection, project_id)

    def write_project_dependencies(self, project_id: int, upserts: list[ProjectDependencyInput], deleted_ids: list[int]) -> None:
        """Apply explicit link changes in the existing transaction."""
        require_current_edit(self.connection, project_id=project_id)
        write_project_dependencies(self.connection, project_id, upserts, deleted_ids)

    def _rows[Record](self, model: Callable[..., Record], source: str,
                      parameters: Sequence[object] = ()) -> list[Record]:
        """Adapt explicit SQL columns at the dynamic driver-to-record boundary."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return [model(**row) for row in cursor.execute(source, parameters)]

    def get_totals(self) -> PlanningTotals:
        """Count visible owners and endpoints before computing planning totals."""
        row = self.connection.execute('''SELECT (SELECT count(*) FROM eppm.project),(SELECT count(*) FROM eppm.current_project_task),
            (SELECT count(*) FROM eppm.effective_task_dependencies)+(SELECT count(*) FROM eppm.effective_project_dependency),
            (SELECT count(DISTINCT pool_id) FROM eppm.active_pool_assignment)''').fetchone()
        return PlanningTotals(projects=row[0], tasks=row[1], dependencies=row[2], pools=row[3])

    def _tasks(self, where: str = '', params: Sequence[object] = ()) -> list[TaskRow]:
        """Use the permanent redacted predecessor projection for all task fields."""
        return self._rows(TaskRow, f'''SELECT {_TASK_COLUMNS},p.task_name AS predecessor_name
            FROM eppm.visible_project_task m LEFT JOIN eppm.current_project_task p ON p.id=m.predecessor_id
            {where} ORDER BY m.project_id,m.start_date,m.id''', params)

    def get_milestones_by_project(self, project_id: int) -> list[TaskRow]:
        """Read one project's visible tasks and primary predecessor labels."""
        return self._tasks('WHERE m.project_id=%s', (project_id,))

    def get_task_correlation_ids(self, project_id: int) -> dict[int, int]:
        """Read stable identities for the exported active plan in one scoped query."""
        return dict(self.connection.execute('''SELECT id,coalesce(stable_task_id,id)
            FROM eppm.current_project_task WHERE project_id=%s''', (project_id,)))

    def get_milestones_for_projects(self, project_ids: list[int]) -> list[TaskRow]:
        """Read only requested tasks using one bound native array."""
        if not project_ids:
            return []
        return self._tasks('WHERE m.project_id=ANY(%s::bigint[])', (project_ids,))

    def get_all_milestones(self) -> list[TaskRow]:
        """Read visible export rows with parent project labels."""
        return self._rows(TaskRow, f'''SELECT {_TASK_COLUMNS},p.name AS project_name
            FROM eppm.visible_project_task m LEFT JOIN eppm.project p ON p.id=m.project_id ORDER BY m.project_id,m.start_date,m.id''')

    def get_milestone_by_id(self, milestone_id: int) -> TaskRow | None:
        """Read a visible task without exposing a hidden primary predecessor."""
        rows = self._rows(TaskRow, f'SELECT {_TASK_COLUMNS} FROM eppm.visible_project_task m WHERE m.id=%s', (milestone_id,))
        return rows[0] if rows else None

    def search_task_choices(self, search: str = '', *, limit: int = 50) -> list[TaskChoice]:
        """Bound selectors to 100 results with exact IDs and literal text searches."""
        search = search.strip()
        if search.lstrip('#').isdigit():
            where, params = 'WHERE t.id=%s', [int(search.lstrip('#'))]
        elif search:
            where = '''WHERE strpos(lower(t.task_name COLLATE "C"),lower(%s::text COLLATE "C"))>0
                       OR strpos(lower(p.name COLLATE "C"),lower(%s::text COLLATE "C"))>0'''
            params = [search, search]
        else:
            where, params = '', []
        return self._rows(TaskChoice, 'SELECT t.id,t.task_name,t.project_id,p.name AS project_name FROM eppm.current_project_task t '
                                     'JOIN eppm.project p ON p.id=t.project_id ' + where + ' ORDER BY t.id DESC LIMIT %s',
                          [*params, max(1, min(100, int(limit)))])

    def _dependencies(self, selected_tasks: str, params: Sequence[object], *, task_label: bool = True) -> list[DependencySchedule]:
        """Join predecessor metadata only after both dependency endpoints pass RLS."""
        label = ',task.task_name' if task_label else ''
        return self._rows(DependencySchedule, f'''WITH selected_tasks AS MATERIALIZED ({selected_tasks})
            SELECT d.id,d.task_id,coalesce(pred.id,d.predecessor_task_id) AS predecessor_task_id,
                   d.predecessor_project_id,d.link_type,d.lag_days,
                   pred.task_name AS predecessor_task_name,to_char(pred.start_date,'YYYY-MM-DD') AS pred_start_date,
                   to_char(pred.end_date,'YYYY-MM-DD') AS pred_end_date,pred.project_id AS pred_task_project_id,
                   p.name AS predecessor_project_name {label}
            FROM selected_tasks task
            JOIN eppm.current_task_dependencies d ON d.task_id=task.id
            LEFT JOIN eppm.project_task original ON original.id=d.predecessor_task_id
            LEFT JOIN LATERAL (
                SELECT coalesce(original.stable_task_id,original.id) AS logical_id OFFSET 0
            ) identity_key ON true
            LEFT JOIN LATERAL (
                SELECT active.id,active.task_name,active.start_date,active.end_date,active.project_id
                FROM eppm.project_task active
                JOIN eppm.project_plan plan ON plan.id=active.project_plan_id AND plan.is_current
                WHERE active.stable_task_id IS NOT NULL
                    AND active.stable_task_id=identity_key.logical_id
                    AND NOT active.is_deleted
                UNION ALL
                SELECT active.id,active.task_name,active.start_date,active.end_date,active.project_id
                FROM eppm.project_task active
                JOIN eppm.project_plan plan ON plan.id=active.project_plan_id AND plan.is_current
                WHERE active.stable_task_id IS NULL
                    AND active.id=identity_key.logical_id
                    AND NOT active.is_deleted OFFSET 0
            ) pred ON true
            LEFT JOIN eppm.project p ON p.id=d.predecessor_project_id ORDER BY d.id''', params)

    def get_dependencies_for_project(self, project_id: int) -> list[DependencySchedule]:
        """Read one project's incoming task and whole-project links."""
        return self.get_dependencies_for_projects([project_id])

    def get_dependencies_for_projects(self, project_ids: list[int]) -> list[DependencySchedule]:
        """Batch incoming links without enumerating unrelated projects."""
        if not project_ids:
            return []
        return self._dependencies('SELECT id,task_name FROM eppm.project_task WHERE project_id=ANY(%s::bigint[]) AND NOT is_deleted AND project_plan_id IN (SELECT id FROM eppm.project_plan WHERE is_current)', (project_ids,))

    def get_task_dependencies(self, task_id: int) -> list[DependencySchedule]:
        """Read one task's incoming links with the existing minimal field contract."""
        return self._dependencies('SELECT id,task_name FROM eppm.project_task WHERE id=%s AND NOT is_deleted AND project_plan_id IN (SELECT id FROM eppm.project_plan WHERE is_current)', (task_id,), task_label=False)

    def get_project_date_bounds(self, project_id: int) -> tuple[str | None, str | None]:
        """Aggregate native dates and retain absent-project null bounds."""
        return self.connection.execute("SELECT to_char(min(start_date),'YYYY-MM-DD'),to_char(max(end_date),'YYYY-MM-DD') "
                                       'FROM eppm.current_project_task WHERE project_id=%s', (project_id,)).fetchone()

    def get_all_project_date_bounds(self) -> ProjectBounds:
        """Expose visible aggregate dates with both integer and chart-string keys."""
        result: ProjectBounds = {}
        for identity, start, end in self.connection.execute("SELECT project_id,to_char(min(start_date),'YYYY-MM-DD'),to_char(max(end_date),'YYYY-MM-DD') "
                                                          'FROM eppm.current_project_task GROUP BY project_id'):
            result[identity] = result[str(identity)] = (start, end)
        return result

    def get_all_external_tasks_map(self, exclude_project_ids: list[int] | None = None) -> dict[str, list[ExternalTask]]:
        """Read minimal visible predecessor exports while excluding requested owners."""
        result: dict[str, list[ExternalTask]] = {}
        for identity, project_id, name, start, end in self.connection.execute('''SELECT id,project_id,task_name,
            to_char(start_date,'YYYY-MM-DD'),to_char(end_date,'YYYY-MM-DD') FROM eppm.current_project_task
            WHERE NOT project_id=ANY(%s::bigint[]) ORDER BY project_id,start_date,id''', (exclude_project_ids or [],)):
            result.setdefault(str(project_id), []).append(ExternalTask(id=identity, task_name=name, start_date=start, end_date=end))
        return result

    def create_task(self, project_id: int, values: TaskValues) -> int:
        """Create normalized native task fields without publishing before commit."""
        require_current_edit(self.connection, project_id=project_id)
        identity = self.connection.execute(_INSERT_TASK + ' RETURNING id', (project_id, project_id, *_task_params(values))).fetchone()[0]
        self.update_progress(identity, values.get('progress_pct', 0))
        return identity

    def update_task(self, task_id: int, values: TaskValues) -> bool:
        """Update task details with native old/new predecessor authorization."""
        if not self.connection.execute('SELECT id FROM eppm.current_project_task WHERE id=%s', (task_id,)).fetchone():
            return False
        require_current_edit(self.connection, task_id=task_id)
        previous = self.connection.execute('SELECT predecessor_id,predecessor_editable FROM eppm.plan_task_edit_access WHERE id=%s', (task_id,)).fetchone()
        predecessor = values.get('predecessor_id')
        if previous and not previous[1]:
            from app.domain.access.models import AccessDenied
            raise AccessDenied()
        if previous and previous[0] != predecessor:
            for endpoint in {previous[0], predecessor} - {None}:
                allowed = self.connection.execute('''SELECT 1 FROM eppm.current_project_task
                    WHERE id=%s AND project_id IN (SELECT unnest(eppm.permission_projects('project.edit')))''', (endpoint,)).fetchone()
                if not allowed:
                    from app.domain.access.models import AccessDenied
                    raise AccessDenied()
        changed = self.connection.execute('''UPDATE eppm.project_task SET task_name=%s,phase=%s,start_date=%s,end_date=%s,
            progress_pct=%s,description=%s,predecessor_id=%s WHERE id=%s''', (*_task_params(values), task_id)).rowcount > 0
        if changed:
            self.update_progress(task_id, values.get('progress_pct', 0))
        return changed

    def insert_dependency(self, task_id: int, dependency: DependencyInput) -> None:
        """Create one normalized link under endpoint ownership checks."""
        require_current_edit(self.connection, task_id=task_id)
        self.connection.execute(_INSERT_DEPENDENCY, _dependency_params(task_id, dependency))

    def replace_dependencies(self, task_id: int, dependencies: list[DependencyInput]) -> None:
        """Replace visible incoming links as one guarded, rollback-safe batch."""
        require_current_edit(self.connection, task_id=task_id)
        self.connection.execute('DELETE FROM eppm.current_task_dependencies WHERE task_id=%s', (task_id,))
        with self.connection.cursor() as cursor:
            cursor.executemany(_INSERT_DEPENDENCY, [_dependency_params(task_id, dependency) for dependency in dependencies])

    def update_dates(self, milestone_id: int, start_date: str, end_date: str) -> bool:
        """Reschedule the live task without changing snapshots or creating a plan."""
        project_id = require_reschedule(self.connection, milestone_id)
        if project_id is None:
            return False
        changed = self.connection.execute('UPDATE eppm.project_task SET start_date=%s,end_date=%s WHERE id=%s',
            (date.fromisoformat(start_date), date.fromisoformat(end_date), milestone_id)).rowcount > 0
        if changed:
            self.connection.execute('UPDATE eppm.project_plan SET revision=revision+1 WHERE project_id=%s AND is_current', (project_id,))
        return changed

    def update_progress(self, milestone_id: int, progress_pct: int) -> bool:
        """Store the existing domain-clamped progress value."""
        if require_reschedule(self.connection, milestone_id) is None:
            return False
        self.connection.execute('''UPDATE eppm.project_plan SET revision=revision+1 WHERE id=
            (SELECT project_plan_id FROM eppm.project_task WHERE id=%s)''', (milestone_id,))
        return self.connection.execute('UPDATE eppm.project_task SET progress_pct=%s WHERE id=%s', (progress_pct, milestone_id)).rowcount > 0

    def bulk_create_milestones(self, rows: list[TaskInput]) -> int:
        """Insert the whole validated import in the surrounding serializable save."""
        for project_id in {row['project_id'] for row in rows}:
            require_current_edit(self.connection, project_id=project_id)
        for row in rows:
            identity = self.connection.execute(_INSERT_TASK + ' RETURNING id',
                (row['project_id'], row['project_id'], *_task_params(row))).fetchone()[0]
            self.update_progress(identity, row.get('progress_pct', 0))
        return len(rows)

    def delete_milestone(self, milestone_id: int) -> bool:
        """Remove visible edges and primary references before deleting the owner."""
        if not self.connection.execute('SELECT id FROM eppm.current_project_task WHERE id=%s', (milestone_id,)).fetchone():
            return False
        require_current_edit(self.connection, task_id=milestone_id)
        self._require_removable([milestone_id])
        self.connection.execute('DELETE FROM eppm.current_task_dependencies WHERE task_id=%s OR predecessor_task_id=%s', (milestone_id, milestone_id))
        self.connection.execute('''UPDATE eppm.project_task SET predecessor_id=NULL WHERE id IN
            (SELECT id FROM eppm.visible_project_task WHERE predecessor_id=%s)''', (milestone_id,))
        self.connection.execute('DELETE FROM eppm.current_resource_pool_assignment WHERE task_id=%s', (milestone_id,))
        self.connection.execute('DELETE FROM eppm.current_task_tag WHERE task_id=%s', (milestone_id,))
        return self.connection.execute('UPDATE eppm.project_task SET is_deleted=true WHERE id=%s', (milestone_id,)).rowcount > 0

    def project_exists(self, project_id: int) -> bool:
        """Check project visibility without hydrating project records."""
        return self.connection.execute('SELECT 1 FROM eppm.project WHERE id=%s', (project_id,)).fetchone() is not None

    def valid_template_references(self, project_id: int, task_ids: set[int], project_ids: set[int]) -> tuple[set[int], set[int]]:
        """Validate external identities in two scoped batches before replacement."""
        tasks = {row[0] for row in self.connection.execute('SELECT id FROM eppm.current_project_task WHERE project_id<>%s AND id=ANY(%s::bigint[])',
                                                         (project_id, sorted(task_ids)))}
        projects = {row[0] for row in self.connection.execute('SELECT id FROM eppm.project WHERE id<>%s AND id=ANY(%s::bigint[])',
                                                            (project_id, sorted(project_ids)))}
        return tasks, projects

    def clear_project_schedule(self, project_id: int) -> None:
        """Remove schedule edges and all project/task allocations in one operation."""
        require_current_edit(self.connection, project_id=project_id)
        self._require_removable([row[0] for row in self.connection.execute(
            'SELECT id FROM eppm.current_project_task WHERE project_id=%s', (project_id,))])
        tasks = 'SELECT id FROM eppm.current_project_task WHERE project_id=%s'
        self.connection.execute(f'DELETE FROM eppm.current_resource_pool_assignment WHERE project_id=%s OR task_id IN ({tasks})', (project_id, project_id))
        self.connection.execute(f'DELETE FROM eppm.current_task_tag WHERE task_id IN ({tasks})', (project_id,))
        self.connection.execute(f'DELETE FROM eppm.current_task_dependencies WHERE task_id IN ({tasks}) OR predecessor_task_id IN ({tasks}) OR predecessor_project_id=%s',
                                (project_id, project_id, project_id))
        self.connection.execute(f'''UPDATE eppm.project_task SET predecessor_id=NULL WHERE id IN
            (SELECT id FROM eppm.visible_project_task WHERE predecessor_id IN ({tasks}))''', (project_id,))
        self.connection.execute('UPDATE eppm.project_task SET is_deleted=true WHERE id IN (SELECT id FROM eppm.current_project_task WHERE project_id=%s)', (project_id,))

    def _require_removable(self, task_ids: list[int]) -> None:
        if self.connection.execute('SELECT 1 FROM eppm.plan_task_edit_access WHERE id=ANY(%s::bigint[]) AND (NOT removable OR NOT predecessor_editable)',
                                   (task_ids,)).fetchone():
            raise PlanningConflictError('The task is referenced by another project outside your edit scope.')

    def related_project_ids(self, project_id: int | list[int], scope: str) -> list[int]:
        """Traverse visible neighbors with one recursive reference and UNION termination."""
        seeds = project_id if isinstance(project_id, list) else [project_id]
        if scope == 'this':
            return [row[0] for row in self.connection.execute('SELECT id FROM eppm.project WHERE id=ANY(%s::bigint[]) ORDER BY id', (seeds,))]
        successors = '''UNION SELECT project_links.successor FROM project_links WHERE project_links.predecessor=selected.id
            UNION SELECT legacy.successor FROM legacy WHERE legacy.predecessor=selected.id
            UNION SELECT task.project_id FROM eppm.effective_task_dependencies d JOIN eppm.current_project_task task ON task.id=d.task_id
                WHERE d.predecessor_project_id=selected.id AND d.predecessor_task_id IS NULL
            UNION SELECT task.project_id FROM eppm.current_project_task pred JOIN eppm.effective_task_dependencies d ON d.predecessor_task_id=pred.id
                JOIN eppm.current_project_task task ON task.id=d.task_id WHERE pred.project_id=selected.id''' if scope == 'all' else ''
        return [row[0] for row in self.connection.execute(f'''WITH RECURSIVE legacy AS MATERIALIZED (
            SELECT task.project_id AS successor,pred.project_id AS predecessor FROM eppm.visible_project_task task
            JOIN eppm.current_project_task pred ON pred.id=task.predecessor_id
        ), project_links AS MATERIALIZED (
            SELECT d.project_id AS successor,coalesce(d.predecessor_project_id,pred.project_id) AS predecessor
            FROM eppm.effective_project_dependency d LEFT JOIN eppm.current_project_task pred ON pred.id=d.predecessor_task_id
        ), selected(id) AS (
            SELECT id FROM eppm.project WHERE id=ANY(%s::bigint[])
            UNION SELECT neighbor.id FROM selected CROSS JOIN LATERAL (
                SELECT legacy.predecessor AS id FROM legacy WHERE legacy.successor=selected.id
                UNION SELECT project_links.predecessor FROM project_links WHERE project_links.successor=selected.id
                UNION SELECT coalesce(pred.project_id,d.predecessor_project_id) FROM eppm.current_project_task task
                    JOIN eppm.effective_task_dependencies d ON d.task_id=task.id LEFT JOIN eppm.current_project_task pred ON pred.id=d.predecessor_task_id
                    WHERE task.project_id=selected.id
                {successors}
            ) neighbor WHERE neighbor.id IS NOT NULL
        ) SELECT id FROM selected ORDER BY id''', (seeds,))]

    def get_project_summaries(self, project_ids: list[int]) -> list[ProjectSummary]:
        """Compute compact scoped headers without using global cached warning flags."""
        return read_project_summaries(self.connection, project_ids)

    def affected_task_projects(self, task_id: int) -> tuple[set[int], set[int]]:
        """Read the visible task's direct dependency owners and consuming pools."""
        row = self.connection.execute('SELECT project_id FROM eppm.current_project_task WHERE id=%s', (task_id,)).fetchone()
        if row is None:
            return set(), set()
        project_id = row[0]
        projects = {project_id} | {row[0] for row in self.connection.execute('''SELECT DISTINCT task.project_id FROM eppm.effective_task_dependencies d
            JOIN eppm.current_project_task task ON task.id=d.task_id WHERE d.predecessor_task_id=%s OR d.predecessor_project_id=%s
            UNION SELECT project_id FROM eppm.effective_project_dependency WHERE predecessor_task_id=%s OR predecessor_project_id=%s''',
            (task_id, project_id, task_id, project_id))}
        pools = {row[0] for row in self.connection.execute('SELECT DISTINCT pool_id FROM eppm.active_pool_assignment WHERE project_id=%s', (project_id,))}
        return projects, pools

    def consuming_pool_ids(self, project_ids: list[int]) -> list[int]:
        """Read distinct positive-demand pools after project-owner filtering."""
        return [row[0] for row in self.connection.execute('''SELECT DISTINCT pool_id FROM eppm.active_pool_assignment
            WHERE fte_assigned>0 AND project_id=ANY(%s::bigint[]) ORDER BY pool_id''', (project_ids,))]

    def read_task_bundle(self, project_ids: list[int]) -> PlanningTaskBundle:
        """Read visible tasks, links, dates, tags and allocations in one snapshot."""
        names = dict(self.connection.execute('SELECT id,name FROM eppm.project WHERE id=ANY(%s::bigint[])', (project_ids,)))
        visible_ids = list(names)
        tasks = self.get_milestones_for_projects(visible_ids)
        task_ids = [task['id'] for task in tasks]
        dependencies = self.get_dependencies_for_projects(visible_ids)
        bound_ids = set(visible_ids) | {link['predecessor_project_id'] for link in dependencies
                                       if link.get('predecessor_project_id') and not link.get('predecessor_task_id')}
        bounds: ProjectBounds = {str(identity): (None, None) for identity in bound_ids}
        bounds.update({str(identity): (start, end) for identity, start, end in self.connection.execute('''SELECT project_id,
            to_char(min(start_date),'YYYY-MM-DD'),to_char(max(end_date),'YYYY-MM-DD') FROM eppm.current_project_task
            WHERE project_id=ANY(%s::bigint[]) GROUP BY project_id''', (sorted(bound_ids),))})
        tags, resources = PostgresTagStore(self.connection), PostgresResourcePoolStore(self.connection)
        return PlanningTaskBundle(tasks, dependencies, tags.get_task_tags_by_task_ids(task_ids), resources.get_task_assignments_map(task_ids),
                                  project_names=names, project_bounds=bounds, project_tags=tags.get_project_tags_by_project_ids(visible_ids),
                                  project_pools=resources.get_project_assignments_map(visible_ids))


class PostgresPlanningGateway:
    """Own complete schedule callbacks, current authorization and safe failures."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess,
                 cache_state: DerivedCacheState | None = None) -> None:
        """Inject the restricted pool, server key and current actor policy."""
        self.database, self.key, self.access = database, key, access
        self.cache = PostgresDerivedCache(database, key, cache_state if cache_state is not None else DerivedCacheState(), access=access)

    def get_project_summaries(self, project_ids: list[int]) -> list[ProjectSummary]:
        """Calculate in repeatable read and publish only against current sources."""
        def calculate(selected: list[int]) -> list[CacheRecord]:
            return [CacheRecord(row['id'], dict(row), dict(row)) for row in
                    self.run(lambda store: store.get_project_summaries(selected))]
        # Headers have no day-dependent values; the cache format uses one fixed
        # day for this projection. Typed dictionaries cross the JSON boundary.
        return cast(list[ProjectSummary], self.cache.load('planning', project_ids, date(2000, 1, 1), calculate))

    def run[Result](self, operation: Callable[[PlanningStore], Result], *, write: bool = False,
                    permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Result:
        """Execute each complete attempt with freshly bound authorization and store."""
        try:
            return run_business(self.database, self.key, self.access, lambda connection: operation(PostgresPlanningStore(connection)),
                                write=write, permission=permission, project_ids=project_ids)
        except psycopg.IntegrityError:
            raise PlanningConflictError('The task change conflicts with an existing reference or constraint.') from None
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Planning storage operation failed (%s)', type(error).__name__)
            raise PlanningStorageError('Planning data could not be accessed. Please try again.') from None
