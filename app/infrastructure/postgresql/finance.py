"""Native immutable finance snapshots with exact Decimal euro amounts."""

from collections.abc import Callable
from decimal import Decimal
import json
from typing import cast

import psycopg

from app.application.exceptions import FinanceStorageError
from app.application.ports.finance import FinanceStore
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, Actor, Permission
from app.domain.finance import BudgetRow, BudgetSnapshot, BudgetVersion, FinanceError
from app.infrastructure.postgresql.access import PostgresAccessStore
from app.infrastructure.postgresql.authorization import ActorBinding, ServerRequestSigner
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import Database
from app.shared.logging import get_logger

logger = get_logger(__name__)
_VERSION_SELECT = """SELECT s.id,s.number,s.name,
    CASE WHEN c.snapshot_id IS NULL THEN s.status ELSE 'Canceled' END,
    s.author,s.created_at,s.base_id,c.author,c.occurred_at,c.previous_status
    FROM eppm.finance_snapshot s LEFT JOIN eppm.finance_cancellation c ON c.snapshot_id=s.id
    WHERE s.sealed"""


class PostgresFinanceStore:
    """Read and append finance history in one active-user transaction snapshot."""

    def __init__(self, connection: psycopg.Connection, access: BusinessAccess,
                 security: PostgresAccessStore, *, writable: bool) -> None:
        """Retain caller-owned connection, current authorization and write capability."""
        self.connection, self.access, self.security, self.writable = connection, access, security, writable

    def versions(self) -> tuple[BudgetVersion, ...]:
        """Read sealed plan metadata with effective cancellation status, newest first."""
        return tuple(BudgetVersion(*row) for row in self.connection.execute(_VERSION_SELECT + ' ORDER BY s.number DESC'))

    def snapshot(self, snapshot_id: int) -> BudgetSnapshot:
        """Read all ordered rows and sparse native euro amounts in two queries."""
        if type(snapshot_id) is not int or not 0 < snapshot_id <= 9223372036854775807:
            raise FinanceError('missing')
        record = self.connection.execute(_VERSION_SELECT + ' AND s.id=%s', (snapshot_id,)).fetchone()
        if record is None:
            raise FinanceError('missing')
        rows: dict[str, dict[int, Decimal]] = {}
        for code, year, amount in self.connection.execute('''SELECT r.code,a.year,a.amount FROM eppm.finance_row r
            LEFT JOIN eppm.finance_amount a ON a.snapshot_id=r.snapshot_id AND a.code=r.code
            WHERE r.snapshot_id=%s ORDER BY r.position,a.year''', (snapshot_id,)):
            values = rows.setdefault(code, {})
            if year is not None:
                values[year] = amount
        return BudgetSnapshot(BudgetVersion(*record), tuple(BudgetRow(code, values) for code, values in rows.items()))

    def catalog(self) -> dict[str, str]:
        """Expose WBS code/description references to active finance readers."""
        return dict(self.connection.execute('SELECT code,description FROM eppm.wbs ORDER BY code COLLATE "C"'))

    def can_edit(self) -> bool:
        """Resolve the current global finance capability independently of project scope."""
        return self.access.global_permission(self.security, Permission.FINANCE)

    def latest(self) -> BudgetVersion | None:
        """Read the latest sealed plan in the current read or write snapshot."""
        row = self.connection.execute(_VERSION_SELECT + ' ORDER BY s.number DESC LIMIT 1').fetchone()
        return BudgetVersion(*row) if row else None

    def _require_write(self) -> None:
        """Reject writes from readers and recheck the finance capability."""
        if not self.writable:
            raise FinanceStorageError('A finance writer transaction is required.')
        self.access.require(self.security, Permission.FINANCE)

    def insert(self, rows: tuple[BudgetRow, ...], *, number: int, name: str,
               status: str, base_id: int | None) -> int:
        """Append and seal a complete plan with its native author/time audit."""
        self._require_write()
        identity = self.connection.execute('''INSERT INTO eppm.finance_snapshot(number,name,status,author,created_at,base_id)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING id''',
            (number, name, status, self.access.audit_actor, self.access.policy.clock(), base_id)).fetchone()[0]
        with self.connection.cursor() as cursor:
            cursor.executemany('INSERT INTO eppm.finance_row(snapshot_id,code,position) VALUES (%s,%s,%s)',
                               [(identity, row.code, index) for index, row in enumerate(rows)])
            cursor.executemany('INSERT INTO eppm.finance_amount(snapshot_id,code,year,amount) VALUES (%s,%s,%s,%s)',
                               [(identity, row.code, year, amount) for row in rows for year, amount in row.amounts.items()])
        self.connection.execute('UPDATE eppm.finance_snapshot SET sealed=true WHERE id=%s', (identity,))
        return identity

    def cancel(self, snapshot_id: int) -> None:
        """Append an immutable cancellation record while retaining the saved plan."""
        self._require_write()
        self.connection.execute('''INSERT INTO eppm.finance_cancellation
            SELECT id,status,%s,%s FROM eppm.finance_snapshot WHERE id=%s AND sealed''',
            (self.access.audit_actor, self.access.policy.clock(), snapshot_id))


class PostgresFinanceGateway:
    """Authorize active-user reads and global writes without requiring project access."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the restricted pool, explicit server key and current user policy."""
        self.database, self.key, self.access = database, key, access

    def run[Result](self, operation: Callable[[FinanceStore], Result], *, write: bool = False) -> Result:
        """Reauthorize complete callbacks on every attempt and expose safe failures."""
        try:
            binding = ActorBinding(self.access, self.key)
            def callback(connection: psycopg.Connection) -> Result:
                actor = cast(Actor, self.access.actor)
                security = PostgresAccessStore(connection, ServerRequestSigner(self.key), self.access.policy, actor, writable=write)
                self.access.policy.session(security, actor)
                if write:
                    self.access.require(security, Permission.FINANCE)
                return operation(PostgresFinanceStore(connection, self.access, security, writable=write))
            try:
                return self.database.run(callback, write=write, bind=binding)
            except psycopg.errors.InsufficientPrivilege:
                raise AccessDenied() from None
        except AccessDenied:
            logger.warning('security.event %s', json.dumps({
                'action': 'finance.authorization_denied', 'outcome': 'denied',
                'actor': self.access.audit_actor, 'correlation': self.access.actor.correlation_id,
                'permission': Permission.FINANCE.value if write else 'active_session',
            }))
            raise
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Finance storage operation failed (%s)', type(error).__name__)
            # Connection loss can make a commit outcome uncertain. Do not promise
            # rollback, retry blindly, or discard the user's submitted draft.
            raise FinanceStorageError('Finance storage is unavailable. Check saved versions before submitting again.') from None
