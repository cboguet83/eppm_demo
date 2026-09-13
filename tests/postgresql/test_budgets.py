"""Native budget report projections and exact, scoped monetary results."""

from decimal import Decimal, localcontext

import psycopg
import pytest

from app.application.exceptions import ProjectStorageError
from app.application.services.budgets import BudgetService
from app.domain.access.models import AccessDenied
from app.infrastructure.postgresql.budgets import PostgresBudgetReader


def reader(authorized, user_id=1):
    return PostgresBudgetReader(authorized.database, authorized.key, access=authorized.binding(user_id).access)


def test_native_budget_report_uses_exact_amounts_and_excludes_hidden_projects(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""UPDATE eppm.project SET planned_budget=CASE id WHEN 1 THEN 0.10 WHEN 2 THEN 0.20 ELSE 999 END,
            actual_budget=CASE id WHEN 1 THEN 0.01 WHEN 2 THEN 0.04 ELSE 888 END""")
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
        connection.execute('UPDATE eppm.project SET planned_budget=NULL,actual_budget=NULL')
    assert BudgetService(reader(authorized)).get_report().metrics.total_actual == Decimal(0)
    authorized.database.close()
    with pytest.raises(ProjectStorageError) as error:
        reader(authorized).read_budgets()
    assert 'postgresql://' not in str(error.value) + caplog.text


def test_high_precision_budget_report_matches_native_numeric_aggregates_under_a_small_context(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET planned_budget=9007199254740993.1234567890123456789,actual_budget=0.0000000000000000001 WHERE id=1")
        connection.execute("UPDATE eppm.project SET planned_budget=0.0000000000000000001,actual_budget=0 WHERE id=2")
        expected = connection.execute('SELECT sum(planned_budget),sum(actual_budget),sum(planned_budget)-sum(actual_budget) FROM eppm.project WHERE id IN (1,2)').fetchone()
        variance = connection.execute('SELECT planned_budget-actual_budget FROM eppm.project WHERE id=1').fetchone()[0]
    with localcontext() as context:
        context.prec = 4
        report = BudgetService(reader(authorized)).get_report()
    assert (report.metrics.total_planned, report.metrics.total_actual, report.metrics.variance) == expected
    assert report.rows[0].analysis.variance == variance


def test_native_portfolio_statistics_preserve_digits_added_by_a_terminating_mean(authorized):
    from app.infrastructure.postgresql.portfolio import PostgresPortfolioReader

    amount = Decimal('12345678901234567890123456789012345')
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project SET planned_budget=0')
        connection.execute('UPDATE eppm.project SET planned_budget=%s WHERE id=1', (amount,))
        connection.execute("INSERT INTO eppm.project(name) SELECT 'Mean item ' || number FROM generate_series(1,61) AS number")
    with localcontext() as context:
        context.prec = 100
        expected = amount / 64
    with localcontext() as context:
        context.prec = 4
        browse = PostgresPortfolioReader(authorized.database, authorized.key, access=authorized.binding(4).access)
        facet = browse.get_facet([{'key': 'planned_budget', 'format': 'currency'}], {}, 'planned_budget')
    assert dict(facet['stats'])['Average'] == expected
