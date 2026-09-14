"""Finance snapshot seeding and active-project WBS shares on real PostgreSQL."""

from datetime import date
from decimal import Decimal

from app.application.ports.maintenance import SeedRequest
from app.infrastructure.postgresql.bulk_seed import generate_projects
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.infrastructure.postgresql.seed_budgets import install_budget_definition
from app.domain.finance import BudgetRow
from app.infrastructure.postgresql.seed_budgets import SEED_BUDGET_NAME, _install_snapshot


def test_missing_proposed_version_uses_retained_approved_amounts(pg_database):
    """Upgrading an existing seed derives proposals from stored financial truth."""
    operator = OperatorDatabase(pg_database.operator_url)
    approved_id = operator.run(lambda c: _install_snapshot(
        c, SEED_BUDGET_NAME, 'Approved',
        (BudgetRow('p.1.10', {2020: Decimal('123.45'), 2021: Decimal('0.01')}),)), write=True)
    operator.run(lambda c: install_budget_definition(c, seed=99), write=True)
    def check(c):
        versions = c.execute('SELECT status,base_id,sealed FROM eppm.finance_snapshot ORDER BY number').fetchall()
        assert versions == [('Approved', None, True), ('Proposed', approved_id, True)]
        amounts = c.execute('''SELECT a.amount,p.amount FROM eppm.finance_amount a
            JOIN eppm.finance_snapshot s ON s.base_id=a.snapshot_id
            JOIN eppm.finance_amount p ON p.snapshot_id=s.id AND p.code=a.code AND p.year=a.year
            WHERE a.snapshot_id=%s ORDER BY a.year''', (approved_id,)).fetchall()
        assert len(amounts) == 2
        assert [value for value, _ in amounts] == [Decimal('123.45'), Decimal('.01')]
        assert all(value * Decimal('.9') <= proposal <= value * Decimal('1.1') for value, proposal in amounts)
        return versions, amounts
    before = operator.run(check)
    operator.run(lambda c: install_budget_definition(c, seed=42), write=True)
    assert operator.run(check) == before


def test_bulk_seed_installs_sealed_budget_and_assigns_only_lowest_active_ids(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(lambda c: generate_projects(c, SeedRequest(projects=30, min_tasks=1, max_tasks=1, random_seed=42),
                                             year=2026, today=date(2026, 9, 14)), write=True)
    def check(c):
        snapshot = c.execute("SELECT id,status,sealed FROM eppm.finance_snapshot WHERE author='demo-seeder' AND status='Approved'").fetchone()
        assert snapshot[1:] == ('Approved', True)
        amounts = c.execute('SELECT code,count(*),min(year),max(year),sum(amount) FROM eppm.finance_amount WHERE snapshot_id=%s GROUP BY code', (snapshot[0],)).fetchall()
        assert len(amounts) == 10
        assert all(count == 10 and last-first == 9 and Decimal(5_000_000) <= total <= Decimal(10_000_000)
                   for _, count, first, last, total in amounts)
        active = [row[0] for row in c.execute("SELECT id FROM eppm.project WHERE status='In Progress' ORDER BY id")]
        shares = c.execute('SELECT p.project_id,w.code,p.percentage FROM eppm.project_wbs p JOIN eppm.wbs w ON w.id=p.wbs_id ORDER BY p.project_id,w.code').fetchall()
        assert shares[:3] == [(active[0], 'p.1.10', 100), (active[1], 'p.2.10', 100), (active[1], 'p.3.10', 50)]
        assert {identity for identity, _, _ in shares} == set(active[:12])
        assert c.execute('SELECT min(total),max(total) FROM (SELECT sum(percentage) total FROM eppm.project_wbs GROUP BY wbs_id) x').fetchone() == (100, 100)
        proposed = c.execute("SELECT id,base_id,sealed FROM eppm.finance_snapshot WHERE author='demo-seeder' AND status='Proposed'").fetchall()
        assert len(proposed) == 1
        assert proposed[0][1:] == (snapshot[0], True)
        comparisons = c.execute('''SELECT a.code,a.year,a.amount,p.amount FROM eppm.finance_amount a
            JOIN eppm.finance_amount p ON p.code=a.code AND p.year=a.year
            WHERE a.snapshot_id=%s AND p.snapshot_id=%s ORDER BY a.code,a.year''',
            (snapshot[0], proposed[0][0])).fetchall()
        assert len(comparisons) == 100
        assert all(approved * Decimal('.9') <= value <= approved * Decimal('1.1')
                   for _, _, approved, value in comparisons)
        return snapshot, shares, amounts, proposed, comparisons
    before = operator.run(check)
    operator.run(lambda c: install_budget_definition(c, seed=99), write=True)
    operator.run(lambda c: generate_projects(c, SeedRequest(projects=10, clean_first=False, random_seed=99), year=2026), write=True)
    assert operator.run(check) == before
