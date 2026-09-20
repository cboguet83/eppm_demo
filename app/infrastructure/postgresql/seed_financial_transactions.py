"""Operator-only, additive demo adjustments against allocated approved budgets."""

from dataclasses import asdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext

import psycopg

from app.domain.financial_transactions import (
    FinancialRecordType, FinancialTransactionInput, normalize_transaction,
)
from app.domain.projects.seed_financial_transactions import ApprovedProjectAmount, spending_targets
from app.infrastructure.postgresql.financial_transactions import PostgresFinancialTransactionStore


def seed_financial_transactions(connection: psycopg.Connection, *, today: date,
                                seed: int, apply: bool = False,
                                project_ids: tuple[int, ...] | None = None) -> dict:
    """Preview or append balancing transactions in the caller's operator transaction.

    Original records, source links, live budgets and approved snapshots remain
    intact. Identical reruns append nothing. Concurrent financial writes and
    changes to approved allocations are blocked while applying the seed.
    When project_ids is supplied, other projects' spending remains untouched.
    """
    if apply:
        connection.execute('''LOCK TABLE eppm.finance_snapshot,eppm.finance_cancellation,
            eppm.finance_amount,eppm.project_wbs,eppm.wbs IN SHARE MODE''')
        connection.execute('LOCK TABLE eppm.project_financial_transaction IN SHARE ROW EXCLUSIVE MODE')
    approved = connection.execute('''SELECT s.id FROM eppm.finance_snapshot s
        WHERE s.status='Approved' AND s.sealed AND NOT EXISTS
        (SELECT 1 FROM eppm.finance_cancellation c WHERE c.snapshot_id=s.id)
        ORDER BY s.number DESC LIMIT 1''').fetchone()
    if not approved:
        raise ValueError('No active approved budget is available for seeding.')
    selected_projects = list(project_ids) if project_ids is not None else None
    with localcontext(prec=60):
        budgets = tuple(ApprovedProjectAmount(project, wbs, year,
            (amount * percentage / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
            for project, wbs, year, amount, percentage in connection.execute('''
                SELECT pw.project_id,w.code,a.year,a.amount,pw.percentage
                FROM eppm.project_wbs pw JOIN eppm.wbs w ON w.id=pw.wbs_id
                JOIN eppm.finance_amount a ON a.code=w.code AND a.snapshot_id=%s
                WHERE pw.percentage>0 AND a.amount>=0
                  AND (%s::bigint[] IS NULL OR pw.project_id=ANY(%s::bigint[]))
                ORDER BY pw.project_id,a.year,w.code''', (approved[0], selected_projects, selected_projects)))
        targets = spending_targets(budgets, year=today.year, seed=seed)
        existing = {(project, wbs, year, kind): amount for project, wbs, year, kind, amount
                    in connection.execute('''SELECT project_id,wbs,fiscal_year,financial_record_type,
                        sum(amount_base_currency) FROM eppm.project_financial_transaction
                        WHERE financial_record_type IN ('ACTUAL','COMMITMENT')
                        GROUP BY project_id,wbs,fiscal_year,financial_record_type''')}
        values = []
        for target in targets:
            cell = target.budget
            for kind, amount in ((FinancialRecordType.ACTUAL, target.actual),
                                  (FinancialRecordType.COMMITMENT, target.commitment)):
                delta = amount - existing.get((cell.project_id, cell.wbs, cell.year, kind), Decimal(0))
                if not delta:
                    continue
                values.append(normalize_transaction(FinancialTransactionInput(
                    project_id=cell.project_id, wbs=cell.wbs, fiscal_year=cell.year,
                    amount=delta, currency='EUR', exchange_rate=Decimal(1),
                    financial_record_type=kind, spending_type='DEMO_SEED',
                    accounting_date=today if cell.year == today.year else date(cell.year, 12, 31),
                    description=f'Demo spending seed {seed}; approved snapshot {approved[0]}; balancing entry',
                )))
    if apply:
        store = PostgresFinancialTransactionStore(connection, writable=True, finance_editor=True)
        for value in values:
            store.create(value, value.amount)
    return {'approved_snapshot_id': approved[0], 'year': today.year, 'seed': seed,
            'projects': len({cell.project_id for cell in budgets}), 'budget_cells': len(budgets),
            'adjustment_count': len(values), 'applied': apply,
            'actual_entries': sum(value.financial_record_type == FinancialRecordType.ACTUAL for value in values),
            'commitment_entries': sum(value.financial_record_type == FinancialRecordType.COMMITMENT for value in values),
            'targets': [asdict(target) for target in targets]}
