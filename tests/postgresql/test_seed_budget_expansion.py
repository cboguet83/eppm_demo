"""Additive budget expansion preserves historical snapshots and existing shares."""

from decimal import Decimal

import psycopg
import pytest

from app.domain.finance import BudgetRow
from app.infrastructure.postgresql.seed_budgets import _install_snapshot
from app.infrastructure.postgresql.seed_budget_expansion import expand_demo_budgets


def test_expansion_preserves_history_derives_proposal_and_maps_only_unmapped_projects(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        approved = _install_snapshot(connection, 'Original approved', 'Approved',
            (BudgetRow('Existing', {2026: Decimal('123.45')}),))
        proposed = _install_snapshot(connection, 'Original proposed', 'Proposed',
            (BudgetRow('Existing', {2026: Decimal('150.00')}),))
        wbs = connection.execute("INSERT INTO eppm.wbs(code) VALUES('Existing') RETURNING id").fetchone()[0]
        connection.execute('INSERT INTO eppm.project_wbs VALUES(1,%s,100)', (wbs,))
        connection.execute("UPDATE eppm.project SET status='Completed' WHERE id=2")
    with psycopg.connect(authorized.setup.operator_url) as connection:
        original = connection.execute('SELECT * FROM eppm.project_wbs ORDER BY project_id,wbs_id').fetchall()
        preview = expand_demo_budgets(connection, high_budget_cap=Decimal('200000000'))
        assert preview['new_wbs'] == 1500 and not preview['applied']
        assert connection.execute('SELECT count(*) FROM eppm.wbs').fetchone() == (1,)
        result = expand_demo_budgets(connection, high_budget_cap=Decimal('200000000'), apply=True)
        assert result['mapped_projects'] == preview['mapped_projects']
        assert connection.execute('SELECT * FROM eppm.project_wbs WHERE project_id=1').fetchall() == original
        for status, old, expected in [('Approved', approved, Decimal('123.45')),
                                      ('Proposed', proposed, Decimal('150.00'))]:
            assert connection.execute("SELECT amount FROM eppm.finance_amount WHERE snapshot_id=%s AND code='Existing'",
                                      (old,)).fetchone() == (expected,)
            assert connection.execute('SELECT count(*) FROM eppm.finance_row WHERE snapshot_id=%s',
                                      (result['created_snapshots'][status],)).fetchone() == (1501,)
        approved_amounts = dict(((code, year), amount) for code, year, amount in connection.execute(
            'SELECT code,year,amount FROM eppm.finance_amount WHERE snapshot_id=%s', (result['created_snapshots']['Approved'],)))
        assert approved_amounts['Existing', 2026] == Decimal('123.45')
        for code, year, amount in connection.execute('SELECT code,year,amount FROM eppm.finance_amount WHERE snapshot_id=%s',
                                                     (result['created_snapshots']['Proposed'],)):
            assert approved_amounts[code, year] * Decimal('.9') <= amount <= approved_amounts[code, year] * Decimal('1.1')
        assert connection.execute('SELECT count(*) FROM eppm.project p WHERE NOT EXISTS '
            '(SELECT 1 FROM eppm.project_wbs pw WHERE pw.project_id=p.id)').fetchone() == (0,)
        assert connection.execute('''SELECT min(a.year),max(a.year),min(pw.percentage)
            FROM eppm.project_wbs pw JOIN eppm.wbs w ON w.id=pw.wbs_id
            JOIN eppm.finance_amount a ON a.code=w.code AND a.snapshot_id=%s
            WHERE pw.project_id=2''', (result['created_snapshots']['Approved'],)).fetchone() == (2020, 2025, 100)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        with pytest.raises(ValueError, match='already exist'):
            expand_demo_budgets(connection, high_budget_cap=Decimal('200000000'), apply=True)
        assert connection.execute('SELECT count(*) FROM eppm.wbs').fetchone() == (1501,)
