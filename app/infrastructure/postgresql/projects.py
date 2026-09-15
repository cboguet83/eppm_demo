"""Native project master data, exact euro amounts and complete atomic edits."""

from collections.abc import Callable, Collection
from typing import cast

import psycopg

from app.application.exceptions import ProjectConflictError, ProjectStorageError
from app.application.ports.business_permissions import PermissionSnapshot
from app.application.ports.projects import PlanningProject, ProjectStore
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor, Permission
from app.domain.projects.links import LinkValues
from app.domain.projects.project import Project
from app.domain.projects.project_types import TemplateProperty, resolve_template
from app.infrastructure.postgresql.access import PostgresAccessStore
from app.infrastructure.postgresql.authorization import ServerRequestSigner
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import Database
from app.infrastructure.postgresql.project_types import PostgresProjectTypeStore
from app.infrastructure.postgresql.property_store import read_values, write_values
from app.infrastructure.postgresql.wbs import PostgresWbsStore
from app.shared.logging import get_logger

logger = get_logger(__name__)


class PostgresProjectStore(PostgresWbsStore):
    """Execute project, property, link and WBS operations in one transaction."""

    def __init__(self, connection: psycopg.Connection,
                 initialize_plan: Callable[[int], None] | None = None) -> None:
        """Inject initial-plan creation into the same project transaction."""
        super().__init__(connection)
        self._initialize_plan = initialize_plan

    def find(self, project_id: int) -> Project | None:
        """Read exact native budgets and all stored values, including inactive ones."""
        row = self.connection.execute('SELECT id,name,status,planned_budget,actual_budget,function_id,project_type_id '
                                      'FROM eppm.project WHERE id=%s', (project_id,)).fetchone()
        if row is None:
            return None
        return Project(row[0], row[1], row[2], row[3], row[4],
                       read_values(self.connection, owner_id=project_id).get(project_id, {}), row[5], row[6])

    def default_type_id(self) -> int:
        """Resolve General inside the current write snapshot."""
        row = self.connection.execute('SELECT id FROM eppm.project_type WHERE is_general').fetchone()
        if row is None:
            raise ValueError('The General project type is missing')
        return row[0]

    def template(self, type_id: int) -> list[TemplateProperty]:
        """Resolve the current effective type using native template projections."""
        store = PostgresProjectTypeStore(self.connection)
        if store.find_type(type_id) is None:
            raise ValueError('Unknown project type')
        return resolve_template(store.property_definitions(), store.selected_properties(type_id),
                                store.required_overrides(type_id), store.defaults(type_id))

    def choices(self) -> dict[str, set[str]]:
        """Batch option validation data for all applicable project properties."""
        result: dict[str, set[str]] = {}
        for param_id, option in self.connection.execute('SELECT param_id,option_value FROM eppm.schema_param_options'):
            result.setdefault(param_id, set()).add(option)
        return result

    def insert(self, project: Project) -> int:
        """Allocate one identity and persist native budgets and typed values atomically."""
        identity = self.connection.execute('SELECT eppm.allocate_project_id(%s)', (project.id,)).fetchone()[0]
        self.connection.execute('INSERT INTO eppm.project(id,name,status,planned_budget,actual_budget,function_id,project_type_id) '
                                'VALUES (%s,%s,%s,%s,%s,%s,%s)',
                                (identity, project.name, project.status, project.planned_budget, project.actual_budget,
                                 project.function_id, project.project_type_id))
        write_values(self.connection, identity, project.dynamic_attributes)
        if self._initialize_plan is not None:
            self._initialize_plan(identity)
        return identity

    def update(self, project: Project) -> None:
        """Update master data and submitted values while retaining inactive properties."""
        self.connection.execute('UPDATE eppm.project SET name=%s,status=%s,planned_budget=%s,actual_budget=%s,function_id=%s,project_type_id=%s WHERE id=%s',
                                (project.name, project.status, project.planned_budget, project.actual_budget,
                                 project.function_id, project.project_type_id, project.id))
        # The master UPDATE has already enforced owner permissions, even for an
        # unchanged form. Preserve full-form validation while avoiding repeated
        # value/item writes and their revision triggers for identical properties.
        write_values(self.connection, project.id, project.dynamic_attributes, skip_unchanged=True)

    def get_links(self, project_id: int) -> list[LinkValues]:
        """Read the visible project's editor link values in creation order."""
        return [LinkValues(url=row[0], alias=row[1]) for row in self.connection.execute(
            'SELECT url,alias FROM eppm.project_link WHERE project_id=%s ORDER BY id', (project_id,))]

    def replace_links(self, project_id: int, links: list[LinkValues]) -> None:
        """Replace validated links within the same project save transaction."""
        self.connection.execute('DELETE FROM eppm.project_link WHERE project_id=%s', (project_id,))
        with self.connection.cursor() as cursor:
            cursor.executemany('INSERT INTO eppm.project_link(project_id,url,alias) VALUES (%s,%s,%s)',
                               [(project_id, link['url'], link['alias']) for link in links])

    def exists(self, project_id: int) -> bool:
        """Test visible existence without loading values or exposing hidden projects."""
        return self.connection.execute('SELECT EXISTS(SELECT 1 FROM eppm.project WHERE id=%s)', (project_id,)).fetchone()[0]

    def next_id(self) -> int:
        """Return a creation-authorized, nonbinding identity preview."""
        return self.connection.execute('SELECT eppm.project_id_preview()').fetchone()[0]

    def delete(self, project_id: int) -> bool:
        """Clear dependency edges and tasks before deleting their owning project."""
        self.connection.execute('DELETE FROM eppm.task_dependencies WHERE predecessor_project_id=%s '
                                'OR task_id IN (SELECT id FROM eppm.project_task WHERE project_id=%s) '
                                'OR predecessor_task_id IN (SELECT id FROM eppm.project_task WHERE project_id=%s)',
                                (project_id, project_id, project_id))
        self.connection.execute('UPDATE eppm.project_task SET predecessor_id=NULL WHERE project_id=%s', (project_id,))
        self.connection.execute('DELETE FROM eppm.project_task WHERE project_id=%s', (project_id,))
        return self.connection.execute('DELETE FROM eppm.project WHERE id=%s', (project_id,)).rowcount > 0


def _planning_catalog(connection: psycopg.Connection, property_ids: tuple[str, ...]) -> list[PlanningProject]:
    """Batch visible identities, requested values and applicability without per-type reads."""
    rows = [PlanningProject(id=row[0], name=row[1], status=row[2], function_id=row[3], project_type_id=row[4],
                            project_template=row[5], dynamic_attributes={}) for row in connection.execute(
        'SELECT p.id,p.name,p.status,p.function_id,p.project_type_id,t.name FROM eppm.project p '
        'JOIN eppm.project_type t ON t.id=p.project_type_id ORDER BY p.id')]
    if not rows or not property_ids:
        return rows
    values = read_values(connection, param_ids=list(property_ids))
    applicability: dict[int, set[str]] = {}
    for type_id, param_id in connection.execute(
        'SELECT t.id,p.param_id FROM eppm.project_type t CROSS JOIN eppm.schema_parameters p '
        'LEFT JOIN eppm.project_type_property membership ON membership.project_type_id=t.id AND membership.param_id=p.param_id '
        'WHERE t.id=ANY(%s::bigint[]) AND p.param_id=ANY(%s::text[]) AND (p.applies_to_all OR membership.project_type_id IS NOT NULL)',
        (list({row['project_type_id'] for row in rows}), list(property_ids)),
    ):
        applicability.setdefault(type_id, set()).add(param_id)
    for row in rows:
        row['dynamic_attributes'] = {param_id: value for param_id, value in values.get(row['id'], {}).items()
                                     if param_id in applicability.get(row['project_type_id'], set())}
    return rows


class PostgresProjectGateway:
    """Own complete project callbacks and consistent permission/catalog projections."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the runtime pool, trusted server key and current actor policy."""
        self.database, self.key, self.access = database, key, access

    def _run[Result](self, operation: Callable[[psycopg.Connection], Result], *, write: bool = False,
                     permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Result:
        """Translate safe errors only after rollback and complete callback replay."""
        try:
            return run_business(self.database, self.key, self.access, operation, write=write,
                                permission=permission, project_ids=project_ids)
        except psycopg.IntegrityError:
            raise ProjectConflictError('The project change conflicts with an existing reference or constraint') from None
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Project storage operation failed (%s)', type(error).__name__)
            raise ProjectStorageError('Project data could not be accessed. Please try again.') from None

    def run[Result](self, operation: Callable[[ProjectStore], Result], *, write: bool = False,
                    permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Result:
        """Execute every attempt with fresh authorization and a caller-owned store."""
        def callback(connection: psycopg.Connection) -> Result:
            from app.domain.planning.plans import PlanContent
            from app.infrastructure.postgresql.project_plans import PostgresPlanStore

            def initialize_plan(project_id: int) -> None:
                security = PostgresAccessStore(connection, ServerRequestSigner(self.key), self.access.policy,
                                               self.access.actor, writable=True)
                PostgresPlanStore(connection, self.access, security).insert(
                    project_id, 'Initial plan', 'approved', None, PlanContent(), current=True)

            return operation(PostgresProjectStore(connection, initialize_plan))
        return self._run(callback, write=write, permission=permission, project_ids=project_ids)

    def read_planning_catalog(self, property_ids: tuple[str, ...]) -> list[PlanningProject]:
        """Read only requested active properties within the visible project snapshot."""
        selected = tuple(property_ids)
        return self._run(lambda connection: _planning_catalog(connection, selected))

    def permission_snapshot(self) -> PermissionSnapshot:
        """Resolve independent UI permissions without crossing transaction snapshots."""
        return self._run(lambda connection: self.access.describe(PostgresAccessStore(
            connection, ServerRequestSigner(self.key), self.access.policy, cast(Actor, self.access.actor), writable=False)))
