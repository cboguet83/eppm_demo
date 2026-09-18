"""Native Decimal project financial persistence with actor-bound row security."""

from collections.abc import Callable, Collection
from dataclasses import fields
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from app.application.exceptions import FinanceStorageError
from app.application.ports.financial_transactions import FinancialTransactionStore
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, Permission
from app.domain.financial_transactions import (
    FinancialRecordType, FinancialTransaction, FinancialTransactionInput, YearlyProjectFinancials,
    PROJECT_EDITOR_RECORD_TYPES,
)
from app.infrastructure.postgresql.access import PostgresAccessStore
from app.infrastructure.postgresql.authorization import ServerRequestSigner
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.pool import Database
from app.shared.logging import get_logger

logger = get_logger(__name__)
_FIELDS = tuple(field.name for field in fields(FinancialTransactionInput))
_EDITABLE = tuple(field for field in _FIELDS if field not in {'project_id', 'financial_record_type'})
_SELECT = 'SELECT id,amount_base_currency,' + ','.join(_FIELDS) + ' FROM eppm.project_financial_transaction'


class PostgresFinancialTransactionStore:
    """Read/write native records within an already authorized transaction."""

    def __init__(self, connection: psycopg.Connection, *, writable: bool, finance_editor: bool) -> None:
        """Retain the caller-owned connection and its write capability."""
        self.connection, self.writable = connection, writable
        self.finance_editor = finance_editor

    def _records(self, where: str, parameters: tuple[object, ...]) -> tuple[FinancialTransaction, ...]:
        # SQL fragments originate only in the fixed methods below, never input.
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(_SELECT + where, parameters)
            return tuple(FinancialTransaction(**(row | {
                'financial_record_type': FinancialRecordType(row['financial_record_type'])})) for row in cursor)

    def get(self, project_id: int, transaction_id: int) -> FinancialTransaction | None:
        """Return a record only when its project is visible in this snapshot."""
        rows = self._records(' WHERE project_id=%s AND id=%s', (project_id, transaction_id))
        return rows[0] if rows else None

    def list(self, project_id: int, fiscal_year: int | None) -> tuple[FinancialTransaction, ...]:
        """Read deterministically ordered records, optionally for one fiscal year."""
        where = ' WHERE project_id=%s'
        parameters = (project_id,)
        if fiscal_year is not None:
            where += ' AND fiscal_year=%s'
            parameters += (fiscal_year,)
        return self._records(where + ' ORDER BY fiscal_year,id', parameters)

    def _require_write(self, record_type: FinancialRecordType) -> None:
        if not self.writable:
            raise FinanceStorageError('A financial transaction writer is required.')
        if not self.finance_editor and record_type not in PROJECT_EDITOR_RECORD_TYPES:
            raise AccessDenied('Project editors can write only COMMITMENT, ACTUAL and LIVE_BUDGET transactions.')

    def require_source(self, transaction_id: int) -> None:
        """Check reference visibility without imposing source type/project rules."""
        if self.connection.execute('SELECT id FROM eppm.project_financial_transaction WHERE id=%s',
                                   (transaction_id,)).fetchone() is None:
            raise AccessDenied('The source transaction is unavailable or not permitted.')

    def create(self, value: FinancialTransactionInput, amount_base_currency: Decimal) -> int:
        """Insert a record and its explicit historical converted value."""
        self._require_write(value.financial_record_type)
        columns = ','.join(_FIELDS) + ',amount_base_currency'
        placeholders = ','.join(['%s'] * (len(_FIELDS) + 1))
        return self.connection.execute(
            f'INSERT INTO eppm.project_financial_transaction({columns}) VALUES ({placeholders}) RETURNING id',
            tuple(getattr(value, field) for field in _FIELDS) + (amount_base_currency,)).fetchone()[0]

    def update(self, transaction_id: int, value: FinancialTransactionInput, amount_base_currency: Decimal) -> bool:
        """Correct mutable fields; never update project ownership or accounting type."""
        self._require_write(value.financial_record_type)
        assignments = ','.join(f'{field}=%s' for field in _EDITABLE) + ',amount_base_currency=%s'
        return self.connection.execute(
            f'UPDATE eppm.project_financial_transaction SET {assignments} WHERE project_id=%s AND id=%s',
            tuple(getattr(value, field) for field in _EDITABLE)
            + (amount_base_currency, value.project_id, transaction_id)).rowcount > 0

    def delete(self, project_id: int, transaction_id: int) -> bool:
        """Remove a record; native foreign keys protect referenced sources."""
        record = self.get(project_id, transaction_id)
        if record is None:
            return False
        self._require_write(record.financial_record_type)
        return self.connection.execute('DELETE FROM eppm.project_financial_transaction WHERE project_id=%s AND id=%s',
                                       (project_id, transaction_id)).rowcount > 0

    def yearly_totals(self, project_ids: Collection[int] | None) -> tuple[YearlyProjectFinancials, ...]:
        """Aggregate only persisted euro values, scoped by RLS before grouping."""
        where = " WHERE financial_record_type IN ('ACTUAL','COMMITMENT')"
        if project_ids is not None:
            where += ' AND project_id=ANY(%s::bigint[])'
        parameters = () if project_ids is None else (list(project_ids),)
        return tuple(YearlyProjectFinancials(*row) for row in self.connection.execute('''
            SELECT project_id,fiscal_year,
                coalesce(sum(amount_base_currency) FILTER (WHERE financial_record_type='ACTUAL'),0),
                coalesce(sum(amount_base_currency) FILTER (WHERE financial_record_type='COMMITMENT'),0)
            FROM eppm.project_financial_transaction''' + where +
            ' GROUP BY project_id,fiscal_year ORDER BY project_id,fiscal_year', parameters))


class PostgresFinancialTransactionGateway:
    """Enforce scoped project editing or finance editing with readable projects."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject the restricted pool and explicit actor/signing dependencies."""
        self.database, self.key, self.access = database, key, access

    def run[Result](self, operation: Callable[[FinancialTransactionStore], Result], *,
                    write: bool = False, project_ids: Collection[int] | None = None) -> Result:
        """Use the shared retry/authorization boundary and expose safe errors."""
        def callback(connection: psycopg.Connection) -> Result:
            finance_editor = False
            if write:
                security = PostgresAccessStore(connection, ServerRequestSigner(self.key),
                                               self.access.policy, self.access.actor, writable=True)
                finance_editor = self.access.global_permission(security, Permission.FINANCE)
                if not finance_editor:
                    self.access.require(security, Permission.EDIT, project_ids)
            return operation(PostgresFinancialTransactionStore(connection, writable=write,
                                                                finance_editor=finance_editor))
        try:
            return run_business(self.database, self.key, self.access, callback, write=write,
                                permission=Permission.READ if project_ids is not None else None,
                                project_ids=project_ids)
        except psycopg.IntegrityError:
            raise ValueError('The financial transaction conflicts with a required value or reference. '
                             'A source transaction cannot be deleted while another transaction references it.') from None
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Financial transaction storage failed (%s)', type(error).__name__)
            raise FinanceStorageError('Financial transaction storage is unavailable. '
                                      'Check saved records before submitting again.') from None
