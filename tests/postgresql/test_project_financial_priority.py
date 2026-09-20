"""Native project priorities and current financial sources preserve access scope."""

from decimal import Decimal
from datetime import date

import psycopg
import pytest

from app.domain.finance import BudgetRow
from app.infrastructure.postgresql.seed_budgets import _install_snapshot
from app.infrastructure.postgresql.portfolio import PostgresPortfolioReader
from app.infrastructure.postgresql.dashboard_catalog import read_catalog
from tests.postgresql.test_projects import projects, gateway
from tests.postgresql.test_financial_transactions import service
from tests.test_financial_transactions import transaction


def test_native_priority_create_edit_and_validation(projects, authorized):
    priorities = projects.strategic_priorities()
    assert list(priorities.values()) == ['Strategic', 'High', 'Medium', 'Low']
    identity = projects.create_project(name='Priority project', strategic_priority_id=1)
    assert projects.get_project_by_id(identity).strategic_priority_id == 1
    assert projects.update_project(identity, 'Updated', 'Draft', {}, strategic_priority_id=4)
    assert projects.get_project_by_id(identity).strategic_priority_id == 4
    for invalid in (True, 99, 'High'):
        with pytest.raises(ValueError, match='strategic priority'):
            projects.create_project(name='Invalid', strategic_priority_id=invalid)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        columns = {r[0] for r in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='eppm' AND table_name='project'")}
        assert 'strategic_priority_id' in columns
        assert not {'planned_budget', 'actual_budget'} & columns
        catalog = read_catalog(connection, [identity])
        assert catalog.projects[0]['fields']['strategic_priority'] == ['4']


def test_portfolio_financial_values_use_all_transactions_and_latest_approved_shares(authorized):
    finance = service(authorized)
    finance.create(transaction(project_id=1, financial_record_type='COMMITMENT', amount=Decimal('20'), fiscal_year=2025))
    finance.create(transaction(project_id=1, financial_record_type='COMMITMENT', amount=Decimal('30'), fiscal_year=2027))
    finance.create(transaction(project_id=1, financial_record_type='ACTUAL', amount=Decimal('7'), fiscal_year=2026))
    finance.create(transaction(project_id=1, financial_record_type='LIVE_BUDGET', amount=Decimal('999'), fiscal_year=2026))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        wbs = connection.execute("INSERT INTO eppm.wbs(code) VALUES('A') RETURNING id").fetchone()[0]
        connection.execute('INSERT INTO eppm.project_wbs VALUES(1,%s,50)', (wbs,))
        _install_snapshot(connection, 'Old', 'Approved', (BudgetRow('A', {2026: Decimal('1000')}),))
        _install_snapshot(connection, 'Latest', 'Approved', (BudgetRow('A', {2025: Decimal('100'), 2027: Decimal('200')}),))
        _install_snapshot(connection, 'Proposal', 'Proposed', (BudgetRow('A', {2026: Decimal('9999')}),))
    reader = PostgresPortfolioReader(authorized.database, authorized.key, access=authorized.binding(1).access)
    page = reader.get_page([], {}, 0)
    row = next(row for row in page['rows'] if row['project_id'] == 1)
    assert row['planned_budget'] == 50 and row['actual_budget'] == 7 and row['approved_budget'] == 150
    assert not any(row['project_id'] == 3 for row in page['rows'])
    revision = reader.revision()
    finance.create(transaction(project_id=1, financial_record_type='ACTUAL', amount=Decimal('3')))
    assert reader.revision() != revision


def test_detail_financials_use_current_year_and_latest_approved(authorized):
    year = date.today().year
    finance = service(authorized)
    for record_type, fiscal_year, amount in (
        ('ACTUAL', year, '25'), ('COMMITMENT', year, '80'),
        ('ACTUAL', year - 1, '999'), ('COMMITMENT', year + 1, '999'),
        ('LIVE_BUDGET', year, '999'),
    ):
        finance.create(transaction(project_id=1, financial_record_type=record_type,
                                   amount=Decimal(amount), fiscal_year=fiscal_year))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        wbs = connection.execute("INSERT INTO eppm.wbs(code) VALUES('A') RETURNING id").fetchone()[0]
        connection.execute('INSERT INTO eppm.project_wbs VALUES(1,%s,50)', (wbs,))
        _install_snapshot(connection, 'Old', 'Approved', (BudgetRow('A', {year: Decimal('999')}),))
        _install_snapshot(connection, 'Latest', 'Approved', (
            BudgetRow('A', {year: Decimal('200'), year + 1: Decimal('999')}),))
        _install_snapshot(connection, 'Proposed', 'Proposed', (BudgetRow('A', {year: Decimal('999')}),))
    reader = PostgresPortfolioReader(authorized.database, authorized.key, access=authorized.binding(1).access)
    row = reader.get_detail(1)
    assert row['financial_year'] == year
    assert row['current_year_approved'] == 100
    assert row['current_year_actual'] == 25
    assert row['current_year_commitment'] == 80
    empty = reader.get_detail(2)
    assert empty['current_year_approved'] == empty['current_year_actual'] == empty['current_year_commitment'] == 0
    assert reader.get_detail(3) is None
