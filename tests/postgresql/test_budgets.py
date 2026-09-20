"""Native budget report projections and exact, scoped monetary results."""

from decimal import Decimal, localcontext

import psycopg
import pytest

from app.application.exceptions import ProjectStorageError
from app.application.services.budgets import BudgetService
from app.domain.access.models import AccessDenied
from app.infrastructure.postgresql.budgets import PostgresBudgetReader
from tests.postgresql.financial_fixtures import set_project_amounts


def reader(authorized, user_id=1):
    return PostgresBudgetReader(authorized.database, authorized.key, access=authorized.binding(user_id).access)


def test_native_budget_report_uses_exact_amounts_and_excludes_hidden_projects(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        for identity, planned, actual in [(1, '.10', '.01'), (2, '.20', '.04'), (3, '999', '888')]:
            set_project_amounts(connection, identity, planned, actual)
    report = BudgetService(reader(authorized)).get_report()
    assert [row.project.id for row in report.rows] == [1, 2]
    assert report.metrics.total_planned == Decimal('0.30') and report.metrics.total_actual == Decimal('0.05')
    assert report.metrics.variance == Decimal('0.25')
    assert report.rows[0].analysis.variance == Decimal('0.09')
    assert type(report.rows[0].project.amounts.planned_budget) is Decimal
    with pytest.raises(AccessDenied):
        reader(authorized, 3).read_budgets()


def test_native_null_budgets_report_as_decimal_zero_and_outages_are_safe(authorized, caplog):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.project_financial_transaction')
    assert BudgetService(reader(authorized)).get_report().metrics.total_actual == Decimal(0)
    authorized.database.close()
    with pytest.raises(ProjectStorageError) as error:
        reader(authorized).read_budgets()
    assert 'postgresql://' not in str(error.value) + caplog.text


def test_high_precision_budget_report_matches_native_numeric_aggregates_under_a_small_context(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        set_project_amounts(connection, 1, '9007199254740993.12', '.01')
        set_project_amounts(connection, 2, '.01', 0)
        expected = (Decimal('9007199254740993.13'), Decimal('.01'), Decimal('9007199254740993.12'))
        variance = Decimal('9007199254740993.11')
    with localcontext() as context:
        context.prec = 4
        report = BudgetService(reader(authorized)).get_report()
    assert (report.metrics.total_planned, report.metrics.total_actual, report.metrics.variance) == expected
    assert report.rows[0].analysis.variance == variance


def test_native_portfolio_statistics_preserve_digits_added_by_a_terminating_mean(authorized):
    from app.infrastructure.postgresql.portfolio import PostgresPortfolioReader

    amount = Decimal('12345678901234567.89')
    with psycopg.connect(authorized.setup.operator_url) as connection:
        set_project_amounts(connection, 1, amount)
        connection.execute("INSERT INTO eppm.project(name) SELECT 'Mean item ' || number FROM generate_series(1,61) AS number")
    with localcontext() as context:
        context.prec = 100
        expected = amount / 64
    with localcontext() as context:
        context.prec = 4
        browse = PostgresPortfolioReader(authorized.database, authorized.key, access=authorized.binding(4).access)
        facet = browse.get_facet([{'key': 'planned_budget', 'format': 'currency'}], {}, 'planned_budget')
    assert dict(facet['stats'])['Average'] == expected
