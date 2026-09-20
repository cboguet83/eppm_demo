"""Decimal budget rules, native PostgreSQL reporting, and budget screen regressions."""

from tests.postgresql.financial_fixtures import create_financed_project
from decimal import Decimal

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from app.domain.projects.budgets import (
    BudgetAmounts,
    analyze_budget,
    euro_amount,
    monetary_statistics,
    summarize_budgets,
)
from app.infrastructure.postgresql.portfolio import PostgresPortfolioReader
from app.main import create_budget_service, create_portfolio_service, create_project_service
from app.presentation.components.budget_frames import budget_frame
from app.runtime import RuntimeResources


@pytest.fixture
def runtime(authorized):
    """Start an empty business catalog in this test's isolated PostgreSQL database."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.project')
    return RuntimeResources(authorized.database, authorized.key)


@pytest.fixture
def access(authorized):
    return authorized.binding(4).access


def test_decimal_budget_totals_preserve_fractional_euros():
    totals = summarize_budgets(
        [
            BudgetAmounts(Decimal("0.1"), Decimal("0.01")),
            BudgetAmounts(Decimal("0.2"), Decimal("0.02")),
        ]
    )
    assert totals.total_projects == 2
    assert totals.total_planned == Decimal("0.3")
    assert totals.total_actual == Decimal("0.03")
    assert totals.variance == Decimal("0.27")
    assert totals.burn_rate == Decimal("10")
    assert summarize_budgets([]).total_projects == 0
    assert summarize_budgets([BudgetAmounts(Decimal(0), Decimal(1))]).burn_rate == 0


@pytest.mark.parametrize(
    "value,expected",
    [(None, "0"), (0.1, "0.1"), (3, "3"), ("12.3400", "12.3400"), (Decimal("0.01"), "0.01")],
)
def test_budget_boundary_converts_storage_and_widget_values_before_arithmetic(value, expected):
    assert euro_amount(value) == Decimal(expected)


@pytest.mark.parametrize("value", ["invalid", True, float("inf"), Decimal("NaN")])
def test_budget_boundary_rejects_nonfinite_or_non_numeric_amounts(value):
    with pytest.raises(ValueError, match="finite numbers"):
        euro_amount(value)


@pytest.mark.parametrize(
    "planned,actual,health,percentage",
    [
        ("100", "84.99", "on_track", "84.99"),
        ("100", "85", "near_capacity", "85"),
        ("100", "100", "near_capacity", "100"),
        ("100", "100.01", "over_budget", "100.01"),
        ("0", "0", "on_track", "0"),
        ("0", "1", "over_budget", None),
    ],
)
def test_budget_health_preserves_thresholds_and_handles_zero_budget(
    planned, actual, health, percentage
):
    analysis = analyze_budget(BudgetAmounts(Decimal(planned), Decimal(actual)))
    assert analysis.health == health
    assert analysis.variance == Decimal(planned) - Decimal(actual)
    assert analysis.burn_rate == (Decimal(percentage) if percentage is not None else None)


def test_monetary_column_statistics_use_decimal_mean():
    assert monetary_statistics([]) is None
    assert monetary_statistics(map(Decimal, ["0.1", "0.2"])) == (
        Decimal("0.1"),
        Decimal("0.15"),
        Decimal("0.2"),
    )


def test_native_budget_report_and_portfolio_totals_share_decimal_rules(runtime, access, authorized):
    projects = create_project_service(runtime, access=access)
    create_financed_project(projects, name="Small A", planned_budget='0.1', actual_budget='0.01')
    create_financed_project(projects, name="Small B", planned_budget='0.2', actual_budget='0.02')
    report = create_budget_service(runtime, access=access).get_report()
    assert report.metrics == create_portfolio_service(runtime, access=access).get_metrics()
    assert report.metrics.total_planned == Decimal("0.3")
    assert report.metrics.variance == Decimal("0.27")
    assert report.rows[0].project.amounts.planned_budget == Decimal("0.1")
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert (
            connection.execute("SELECT pg_typeof(amount_base_currency)::text FROM eppm.project_financial_transaction LIMIT 1").fetchone()[0]
            == "numeric"
        )
    facet = PostgresPortfolioReader(runtime.database, runtime.key, access=access).get_facet(
        [{"key": "planned_budget", "format": "currency"}],
        {},
        "planned_budget",
    )
    assert dict(facet["stats"])["Average"] == Decimal('0.15')


def test_budget_report_rows_and_totals_share_a_concurrent_snapshot(runtime, access, authorized, monkeypatch):
    import app.infrastructure.postgresql.budgets as adapter

    projects = create_project_service(runtime, access=access)
    create_financed_project(projects, name="First", planned_budget=10, actual_budget=1)
    create_financed_project(projects, name="Second", planned_budget=20, actual_budget=2)
    convert = adapter.BudgetAmounts
    changed = False

    def change_after_read(planned, actual):
        nonlocal changed
        if not changed:
            changed = True
            with psycopg.connect(authorized.setup.operator_url) as writer:
                writer.execute("UPDATE eppm.project_financial_transaction SET amount=200,amount_base_currency=200 WHERE financial_record_type='ACTUAL' AND project_id=(SELECT id FROM eppm.project WHERE name='Second')")
        return convert(planned, actual)

    with monkeypatch.context() as patch:
        patch.setattr(adapter, "BudgetAmounts", change_after_read)
        report = create_budget_service(runtime, access=access).get_report()
    assert report.metrics.total_actual == Decimal(3)
    assert report.rows[1].project.amounts.actual_budget == Decimal(2)
    assert create_budget_service(runtime, access=access).get_report().metrics.total_actual == Decimal(201)




def budget_screen(service):
    """Render the production page with its real actor-bound native service."""
    from app.presentation.pages.budgets import render_budget_tracking
    from app.presentation.i18n import set_current_locale

    set_current_locale('en')
    render_budget_tracking(service)


def render_budget(runtime, access):
    service = create_budget_service(runtime, access=access)
    return AppTest.from_function(budget_screen, args=(service,), default_timeout=15).run()


def test_budget_screen_renders_integer_project_ids_and_computed_health(runtime, access):
    projects = create_project_service(runtime, access=access)
    first = create_financed_project(projects, name="On track", planned_budget=100, actual_budget=10)
    second = create_financed_project(projects, name="Near", planned_budget=100, actual_budget=85)
    app = render_budget(runtime, access)
    assert not app.exception
    assert len(app.get("plotly_chart")) == 3
    assert len(app.success) == 1
    assert app.metric[0].value == "€200.00"
    assert app.metric[2].value == "€105.00"
    rows = app.dataframe[0].value
    assert rows["id"].tolist() == [str(first), str(second)]
    assert rows["health_status"].tolist() == ["🟢 On Track", "🟡 Near Capacity"]


def test_budget_screen_displays_overspend_without_infinite_zero_budget_percentage(runtime, access):
    create_financed_project(create_project_service(runtime, access=access),
        name="No budget", planned_budget=0, actual_budget=5
    )
    report = create_budget_service(runtime, access=access).get_report()
    assert budget_frame(report).iloc[0]["burn_rate_pct"] is None
    app = render_budget(runtime, access)
    assert not app.exception
    assert "€5.00" in app.warning[0].value
    assert app.dataframe[0].value["burn_rate_pct"].isna().all()
    assert app.dataframe[0].value["health_status"].tolist() == ["🔴 Over Budget"]


def test_budget_screen_handles_empty_database_and_safe_read_errors(runtime, access):
    empty = render_budget(runtime, access)
    assert not empty.exception
    assert empty.info and not empty.metric
    runtime.database.close()
    failed = render_budget(runtime, access)
    assert not failed.exception
    assert failed.error and not failed.metric
    assert "postgresql://" not in failed.error[0].value
