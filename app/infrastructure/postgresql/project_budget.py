"""Atomic project/WBS budget views and unversioned live budget persistence."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json

import psycopg

from app.application.exceptions import FinanceStorageError
from app.application.ports.project_budget import ProjectBudgetStore
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, Permission
from app.domain.dashboard import WbsShare, allocated_budget
from app.domain.financial_transactions import FinancialRecordType, FinancialTransactionInput, converted_amount, normalize_transaction
from app.domain.project_budget import ProjectBudgetRow, ProjectBudgetView, ROW_LABELS
from app.infrastructure.postgresql.access import PostgresAccessStore
from app.infrastructure.postgresql.authorization import ServerRequestSigner
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError
from app.infrastructure.postgresql.finance import PostgresFinanceStore
from app.infrastructure.postgresql.financial_transactions import PostgresFinancialTransactionStore
from app.infrastructure.postgresql.pool import Database
from app.shared.logging import get_logger

logger = get_logger(__name__)


class PostgresProjectBudgetStore:
    """Compose shared approved/proposed snapshots with project-specific amounts."""

    def __init__(self, connection: psycopg.Connection, project_id: int, access: BusinessAccess,
                 security: PostgresAccessStore, *, writable: bool) -> None:
        """Keep all reads, permission checks and writes in the caller's transaction."""
        self.connection, self.project_id = connection, project_id
        self.access, self.security = access, security
        self.finance = PostgresFinanceStore(connection, access, security, writable=False)
        self.transactions = PostgresFinancialTransactionStore(connection, writable=writable, finance_editor=False)

    def view(self) -> ProjectBudgetView:
        """Read five rows per WBS, including codes found only in transactions."""
        shares = [WbsShare(*row) for row in self.connection.execute('''
            SELECT pw.project_id,w.code,pw.percentage::integer
            FROM eppm.project_wbs pw JOIN eppm.wbs w ON w.id=pw.wbs_id
            WHERE pw.project_id=%s ORDER BY w.code COLLATE "C"''', (self.project_id,))]
        codes = {share.code for share in shares}
        values, versions = {}, {}
        for identity, status in self.connection.execute('''
            SELECT DISTINCT ON (s.status) s.id,s.status FROM eppm.finance_snapshot s
            WHERE s.sealed AND s.status IN ('Approved','Proposed') AND NOT EXISTS
            (SELECT 1 FROM eppm.finance_cancellation c WHERE c.snapshot_id=s.id)
            ORDER BY s.status,s.number DESC'''):
            snapshot = self.finance.snapshot(identity)
            versions[status] = str(snapshot.version.number)
            for share, amounts in allocated_budget(shares, snapshot, date.today().year).rows:
                values[share.code, status] = amounts
        for wbs, kind, year, amount in self.connection.execute('''
            SELECT wbs,financial_record_type,fiscal_year,sum(amount_base_currency)
            FROM eppm.project_financial_transaction WHERE project_id=%s
            AND financial_record_type IN ('LIVE_BUDGET','ACTUAL','COMMITMENT')
            GROUP BY wbs,financial_record_type,fiscal_year''', (self.project_id,)):
            codes.add(wbs)
            values.setdefault((wbs, kind), {})[year] = amount
        rows = tuple(ProjectBudgetRow(code, kind, versions.get(kind, ''), values.get((code, kind), {}))
                     for code in sorted(codes) for kind in ROW_LABELS)
        token = json.dumps([(row.wbs, row.kind, row.version, row.amounts) for row in rows],
                           default=str, sort_keys=True)
        try:
            self.access.require(self.security, Permission.EDIT, [self.project_id])
            can_edit = True
        except AccessDenied:
            can_edit = False
        return ProjectBudgetView(self.project_id, rows, sha256(token.encode()).hexdigest(), can_edit)

    def set_live_budget(self, wbs: str, year: int, amount: Decimal | None) -> None:
        """Replace the single live cell without creating a budget revision."""
        record = self.connection.execute('''SELECT id FROM eppm.project_financial_transaction
            WHERE project_id=%s AND wbs=%s AND fiscal_year=%s AND financial_record_type='LIVE_BUDGET' ''',
            (self.project_id, wbs, year)).fetchone()
        if amount is None:
            if record:
                self.transactions.delete(self.project_id, record[0])
            return
        value = normalize_transaction(FinancialTransactionInput(
            project_id=self.project_id, wbs=wbs, fiscal_year=year, amount=amount,
            currency='EUR', exchange_rate=Decimal(1),
            financial_record_type=FinancialRecordType.LIVE_BUDGET, spending_type='LIVE_BUDGET'))
        if record:
            self.transactions.update(record[0], value, converted_amount(amount, Decimal(1)))
        else:
            self.transactions.create(value, converted_amount(amount, Decimal(1)))

    def create_adjustment(self, value: FinancialTransactionInput) -> None:
        """Append a correction while retaining actual/commitment source history."""
        self.transactions.create(value, converted_amount(value.amount, value.exchange_rate))


class PostgresProjectBudgetGateway:
    """Reauthorize each project read/write, including Business Administrator writes."""

    def __init__(self, database: Database, key: bytes, *, access: BusinessAccess) -> None:
        """Inject restricted persistence and current request authorization."""
        self.database, self.key, self.access = database, key, access

    def run[Result](self, project_id: int, operation: Callable[[ProjectBudgetStore], Result], *,
                    write: bool = False) -> Result:
        """Execute the complete operation under one serializable authorized snapshot."""
        def callback(connection: psycopg.Connection) -> Result:
            security = PostgresAccessStore(connection, ServerRequestSigner(self.key),
                                           self.access.policy, self.access.actor, writable=write)
            return operation(PostgresProjectBudgetStore(connection, project_id, self.access, security, writable=write))
        try:
            return run_business(self.database, self.key, self.access, callback, write=write,
                                permission=Permission.EDIT if write else Permission.READ, project_ids=[project_id])
        except psycopg.IntegrityError:
            raise ValueError('The budget conflicts with an existing value or reference. Reload before saving.') from None
        except (psycopg.Error, DatabaseUnavailableError, TransactionRetryError) as error:
            logger.error('Project budget storage failed (%s)', type(error).__name__)
            raise FinanceStorageError('Project budget storage is unavailable. Reload before submitting again.') from None
