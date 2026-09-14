"""Native dashboard reads with private aggregate-only competing demand."""

from collections.abc import Callable
from datetime import date
import json

import psycopg
from psycopg.rows import dict_row

from app.application.exceptions import ProjectStorageError
from app.application.ports.dashboard import DashboardCatalog, DashboardData, ResourceBreakdown
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, Actor
from app.domain.dashboard import WbsShare, quarter_bounds
from app.infrastructure.postgresql.access import PostgresAccessStore
from app.infrastructure.postgresql.authorization import ActorBinding, ServerRequestSigner
from app.infrastructure.postgresql.dashboard_catalog import read_catalog
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.finance import PostgresFinanceStore
from app.infrastructure.postgresql.pool import Database
from app.shared.logging import get_logger


logger = get_logger(__name__)
_LATEST = '''SELECT s.id FROM eppm.finance_snapshot s WHERE s.sealed AND s.status=%s
    AND NOT EXISTS(SELECT 1 FROM eppm.finance_cancellation c WHERE c.snapshot_id=s.id) ORDER BY s.number DESC LIMIT 1'''
_BLOCKERS = '''FROM eppm.project_log_event e JOIN eppm.project p ON p.id=e.project_id
    JOIN eppm.project_event_type t ON t.id=e.event_type_id WHERE t.system_code='blocking_point'
    AND e.status='active' AND e.project_id=ANY(%s::bigint[])'''


class PostgresDashboardReader:
    """Reauthorize empty dashboards and explicit requested scopes in each snapshot."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the restricted process pool and actual signed request actor."""
        self.database, self.key, self.access = database, key, access

    def _run[Result](self, operation: Callable[[psycopg.Connection, list[int], PostgresAccessStore], Result],
                     requested: list[int] | None = None) -> Result:
        """Preserve the dashboard's active-session empty-scope behavior safely."""
        requested = list(requested) if requested is not None else None
        try:
            actor = self.access.actor
            if not isinstance(actor, Actor):
                raise AccessDenied()
            def callback(connection: psycopg.Connection) -> Result:
                security = PostgresAccessStore(connection, ServerRequestSigner(self.key), self.access.policy, actor, writable=False)
                self.access.policy.session(security, actor)
                allowed = self.access.policy.projects(security, actor)
                if requested is not None and (any(type(value) is not int for value in requested) or not set(requested) <= allowed):
                    raise AccessDenied()
                return operation(connection, sorted(allowed if requested is None else set(requested)), security)
            try:
                return self.database.run(callback, bind=ActorBinding(self.access, self.key))
            except psycopg.errors.InsufficientPrivilege:
                raise AccessDenied() from None
        except AccessDenied:
            logger.warning('security.event %s', json.dumps({'action': 'dashboard.authorization_denied', 'outcome': 'denied',
                'actor': self.access.audit_actor, 'correlation': self.access.actor.correlation_id, 'permission': 'dashboard.read'}))
            raise
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Dashboard storage operation failed (%s)', type(error).__name__)
            raise ProjectStorageError('Dashboard data is unavailable. Please try again.') from None

    def revision(self) -> tuple:
        """Hash visible sources, relevant competing demand and latest finance statuses."""
        return self._run(lambda connection, _ids, _security: (connection.execute('SELECT eppm.dashboard_revision()').fetchone()[0],))

    def catalog(self) -> DashboardCatalog:
        """Read current project/filter fields without exposing unrelated labels."""
        return self._run(lambda connection, ids, _security: read_catalog(connection, ids))

    def data(self, project_ids: list[int], status: str = 'Approved') -> DashboardData:
        """Read authorized WBS shares, active blockers and the requested latest plan."""
        if status not in {'Approved', 'Proposed', 'Draft'}:
            raise ValueError('Select Approved, Proposed, or Draft.')
        def operation(connection: psycopg.Connection, ids: list[int], security: PostgresAccessStore) -> DashboardData:
            shares = [WbsShare(*row) for row in connection.execute('''SELECT pw.project_id,w.code,pw.percentage::integer
                FROM eppm.project_wbs pw JOIN eppm.wbs w ON w.id=pw.wbs_id
                WHERE pw.project_id=ANY(%s::bigint[]) ORDER BY pw.project_id,w.code COLLATE "C"''', (ids,))]
            latest = connection.execute(_LATEST, (status,)).fetchone() if ids else None
            approved = PostgresFinanceStore(connection, self.access, security, writable=False).snapshot(latest[0]) if latest else None
            count = connection.execute('SELECT count(*) ' + _BLOCKERS, (ids,)).fetchone()[0]
            return DashboardData(shares, approved, count)
        return self._run(operation, project_ids)

    def shortages(self, project_ids: list[int], today: date) -> dict[str, float]:
        """Return quarterly peak shortfalls including safe competing-demand totals."""
        return self.resources(project_ids, today)['overallocation']

    def resources(self, project_ids: list[int], today: date) -> dict[str, dict[str, float]]:
        """Receive only quarterly totals from the privileged aggregate boundary."""
        def operation(connection: psycopg.Connection, ids: list[int], _security: PostgresAccessStore) -> dict[str, dict[str, float]]:
            row = connection.execute('SELECT eppm.dashboard_resources(%s::bigint[],%s)', (ids, today)).fetchone()[0]
            return {key: {quarter: float(value) for quarter, value in row[key].items()} for key in ('overallocation', 'capacity')}
        return self._run(operation, project_ids)

    def resource_breakdown(self, project_ids: list[int], today: date) -> ResourceBreakdown:
        """Read safe pool contributions while retaining competing-demand privacy."""
        def operation(connection: psycopg.Connection, ids: list[int], _security: PostgresAccessStore) -> ResourceBreakdown:
            result = connection.execute('SELECT eppm.dashboard_resource_breakdown(%s::bigint[],%s)', (ids, today)).fetchone()[0]
            return ResourceBreakdown(allocation=result['allocation'], overallocation=result['overallocation'],
                capacity=result['capacity'], pools=result['pools'], peak_days=result.get('peak_days', {}))
        return self._run(operation, project_ids)

    def consuming_projects(self, project_ids: list[int], quarter: str, today: date,
                           pool_id: int | None = None, metric: str = 'overallocation') -> list[int]:
        """Return only currently visible consumers of the quarter's responsible pools."""
        quarter_bounds(quarter, today.year)
        if pool_id is not None and (type(pool_id) is not int or pool_id <= 0):
            raise ValueError('Select a valid resource pool.')
        if metric not in {'overallocation', 'allocation'}:
            raise ValueError('Select a valid resource metric.')
        return self._run(lambda connection, ids, _security: connection.execute(
            'SELECT eppm.dashboard_resource_breakdown(%s::bigint[],%s,%s,%s,%s)',
            (ids, today, quarter, pool_id, metric)).fetchone()[0]['consumers'], project_ids)

    def issues(self, project_ids: list[int], locale: str) -> list[dict]:
        """Read localized active blockers with the established ISO date boundaries."""
        def operation(connection: psycopg.Connection, ids: list[int], _security: PostgresAccessStore) -> list[dict]:
            with connection.cursor(row_factory=dict_row) as cursor:
                return cursor.execute("""SELECT e.id,e.project_id,e.title,e.description,to_char(e.deadline,'YYYY-MM-DD') AS deadline,
                    e.scope,e.comment,e.event_type_id,e.status,
                    to_char(e.created_at AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') AS created_at,
                    to_char(e.updated_at AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') AS updated_at,
                    p.name AS project_name,coalesce((SELECT label FROM eppm.project_event_type_translation
                        WHERE catalog_id=t.id AND locale=%s),t.name) AS event_type """ + _BLOCKERS +
                    ' ORDER BY e.project_id,e.id DESC', (locale, ids)).fetchall()
        return self._run(operation, project_ids)
