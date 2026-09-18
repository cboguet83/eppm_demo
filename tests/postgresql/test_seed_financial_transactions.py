"""Operator seed preserves original records and reruns without duplication."""

from datetime import date
from decimal import Decimal

import psycopg
import pytest

from app.domain.finance import BudgetRow
from app.infrastructure.postgresql.seed_budgets import _install_snapshot
from app.infrastructure.postgresql.seed_financial_transactions import seed_financial_transactions
from tests.postgresql.test_financial_transactions import service
from tests.test_financial_transactions import transaction


def test_preview_apply_and_repeat_preserve_existing_transactions_and_live_budgets(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        snapshot = _install_snapshot(connection, 'Approved', 'Approved', (
            BudgetRow('A', {2025: Decimal('1000'), 2026: Decimal('1000'), 2027: Decimal('1000')}),
            BudgetRow('B', {2025: Decimal('3000'), 2026: Decimal('3000'), 2027: Decimal('3000')})))
        _install_snapshot(connection, 'Proposed', 'Proposed', (BudgetRow('A', {2026: Decimal('9999')}),))
        connection.execute("INSERT INTO eppm.wbs(id,code) VALUES(1,'A'),(2,'B')")
        connection.execute('INSERT INTO eppm.project_wbs VALUES(1,1,50),(1,2,50),(2,1,50)')
    finance = service(authorized)
    commitment = finance.create(transaction(wbs='A', amount=Decimal('10000')))
    finance.create(transaction(wbs='A', amount=Decimal('100'), financial_record_type='ACTUAL',
                               source_transaction_id=commitment))
    live = finance.create(transaction(wbs='A', financial_record_type='LIVE_BUDGET'))
    original = finance.list(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        before = connection.execute('SELECT * FROM eppm.finance_amount ORDER BY snapshot_id,code,year').fetchall()
        preview = seed_financial_transactions(connection, today=date(2026, 9, 18), seed=18)
        assert preview['approved_snapshot_id'] == snapshot
        assert preview['projects'] == 2 and preview['budget_cells'] == 9
        assert preview['adjustment_count'] > 0
        assert connection.execute('SELECT count(*) FROM eppm.project_financial_transaction').fetchone() == (3,)
        applied = seed_financial_transactions(connection, today=date(2026, 9, 18), seed=18, apply=True)
        assert applied == preview | {'applied': True}
        again = seed_financial_transactions(connection, today=date(2026, 9, 18), seed=18, apply=True)
        assert again['adjustment_count'] == 0
        assert before == connection.execute('SELECT * FROM eppm.finance_amount ORDER BY snapshot_id,code,year').fetchall()
        amounts = {(project, wbs, year, kind): amount for project, wbs, year, kind, amount in connection.execute('''
            SELECT project_id,wbs,fiscal_year,financial_record_type,sum(amount_base_currency)
            FROM eppm.project_financial_transaction GROUP BY project_id,wbs,fiscal_year,financial_record_type''')}
        for target in applied['targets']:
            cell = target['budget']
            for kind, key in [('ACTUAL', 'actual'), ('COMMITMENT', 'commitment')]:
                assert amounts.get((cell['project_id'], cell['wbs'], cell['year'], kind), 0) == target[key]
        assert any(value.amount < 0 for value in finance.list(1)) is False  # uncommitted seed stays isolated
    assert all(finance.get(1, record.id) == record for record in original)
    assert finance.get(1, live).financial_record_type == 'LIVE_BUDGET'
    assert any(value.amount < 0 for value in finance.list(1))


def test_no_approved_budget_fails_without_writes(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        with pytest.raises(ValueError, match='No active approved'):
            seed_financial_transactions(connection, today=date(2026, 9, 18), seed=1, apply=True)
        assert connection.execute('SELECT count(*) FROM eppm.project_financial_transaction').fetchone() == (0,)
