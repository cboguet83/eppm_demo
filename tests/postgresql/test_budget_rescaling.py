"""Scaling creates new revisions, preserves history, and guards repeat runs."""

from decimal import Decimal

import psycopg
import pytest

from app.domain.finance import BudgetRow
from app.infrastructure.postgresql.seed_budgets import _install_snapshot
from app.infrastructure.postgresql.seed_budget_expansion import scale_current_budgets


def test_approved_and_proposed_are_scaled_independently_and_history_is_preserved(pg_database):
    with psycopg.connect(pg_database.operator_url) as connection:
        approved = _install_snapshot(connection, 'Approved name', 'Approved', (
            BudgetRow('A', {2025: Decimal('10000'), 2026: Decimal('10')}),))
        proposed = _install_snapshot(connection, 'Proposed name', 'Proposed', (
            BudgetRow('A', {2025: Decimal('10999'), 2027: Decimal('9.99')}), BudgetRow('Empty', {})))
        original = connection.execute('SELECT * FROM eppm.finance_amount ORDER BY snapshot_id,code,year').fetchall()
        with pytest.raises(ValueError, match='latest Proposed'):
            scale_current_budgets(connection, approved_id=approved, proposed_id=999)
        assert connection.execute('SELECT count(*) FROM eppm.finance_snapshot').fetchone() == (2,)
        created = scale_current_budgets(connection, approved_id=approved, proposed_id=proposed)
        assert connection.execute('SELECT * FROM eppm.finance_amount WHERE snapshot_id=ANY(%s) ORDER BY snapshot_id,code,year', ([approved, proposed],)).fetchall() == original
        assert connection.execute('SELECT year,amount FROM eppm.finance_amount WHERE snapshot_id=%s ORDER BY year', (created['Approved'],)).fetchall() == [(2025, Decimal(500)), (2026, Decimal(1))]
        assert connection.execute('SELECT year,amount FROM eppm.finance_amount WHERE snapshot_id=%s ORDER BY year', (created['Proposed'],)).fetchall() == [(2025, Decimal(550)), (2027, Decimal(0))]
        assert connection.execute('SELECT code FROM eppm.finance_row WHERE snapshot_id=%s ORDER BY position', (created['Proposed'],)).fetchall() == [('A',), ('Empty',)]
        with pytest.raises(ValueError, match='latest Approved'):
            scale_current_budgets(connection, approved_id=approved, proposed_id=proposed)
