"""Decimal budget rules, real SQLite reporting, and budget screen regressions."""

from contextlib import closing
from decimal import Decimal

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app.domain.projects.budgets import (
    BudgetAmounts,
    analyze_budget,
    euro_amount,
    monetary_statistics,
    summarize_budgets,
)
from app.infrastructure.database.connection import get_db
from app.infrastructure.repositories.portfolio import SqlitePortfolioReader
from app.main import create_budget_service, create_portfolio_service, create_project_service
from app.presentation.components.budget_frames import budget_frame, calculate_frame_metrics
from src.database.schema_init import init_db


@pytest.fixture
def database(tmp_path):
    path = str(tmp_path / "budgets.db")
    init_db(path)
    return path


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
def test_budget_boundary_converts_compatibility_values_before_arithmetic(value, expected):
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


def test_sqlite_budget_report_and_portfolio_totals_share_decimal_rules(database):
    projects = create_project_service(database)
    projects.create_project(name="Small A", planned_budget=0.1, actual_budget=0.01)
    projects.create_project(name="Small B", planned_budget=0.2, actual_budget=0.02)
    report = create_budget_service(database).get_report()
    assert report.metrics == create_portfolio_service(database).get_metrics()
    assert report.metrics.total_planned == Decimal("0.3")
    assert report.metrics.variance == Decimal("0.27")
    assert report.rows[0].project.amounts.planned_budget == Decimal("0.1")
    with closing(get_db(database)) as connection:
        assert (
            connection.execute("SELECT typeof(planned_budget) FROM project LIMIT 1").fetchone()[0]
            == "real"
        )
    facet = SqlitePortfolioReader(database).get_facet(
        [{"key": "planned_budget", "format": "currency"}],
        {},
        "planned_budget",
    )
    assert dict(facet["stats"])["Average"] == 0.15


def test_budget_report_rows_and_totals_share_a_concurrent_snapshot(database, monkeypatch):
    import app.infrastructure.repositories.budgets as adapter

    projects = create_project_service(database)
    projects.create_project(name="First", planned_budget=10, actual_budget=1)
    projects.create_project(name="Second", planned_budget=20, actual_budget=2)
    with closing(get_db(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    convert = adapter.euro_amount
    changed = False

    def change_after_read(value):
        nonlocal changed
        if not changed:
            changed = True
            with closing(get_db(database)) as writer, writer:
                writer.execute("UPDATE project SET actual_budget=200 WHERE name='Second'")
        return convert(value)

    with monkeypatch.context() as patch:
        patch.setattr(adapter, "euro_amount", change_after_read)
        report = create_budget_service(database).get_report()
    assert report.metrics.total_actual == Decimal(3)
    assert report.rows[1].project.amounts.actual_budget == Decimal(2)
    assert create_budget_service(database).get_report().metrics.total_actual == Decimal(201)


def test_legacy_budget_frame_metrics_skip_missing_values_without_float_sums():
    frame = pd.DataFrame({"planned_budget": [0.1, 0.2, None], "actual_budget": [None, 0.1, 0.2]})
    assert calculate_frame_metrics(frame).variance == Decimal(0)
    assert calculate_frame_metrics(frame).total_projects == 3
    assert calculate_frame_metrics(pd.DataFrame()).total_projects == 0


def render_budget(database):
    return AppTest.from_string(
        f"""
from app.main import create_budget_service
from app.presentation.pages.budgets import render_budget_tracking
from src.i18n import set_current_locale
set_current_locale('en')
render_budget_tracking(create_budget_service({database!r}))
""",
        default_timeout=15,
    ).run()


def test_budget_screen_renders_integer_project_ids_and_computed_health(database):
    projects = create_project_service(database)
    projects.create_project(name="On track", planned_budget=100, actual_budget=10)
    projects.create_project(name="Near", planned_budget=100, actual_budget=85)
    app = render_budget(database)
    assert not app.exception
    assert len(app.get("plotly_chart")) == 3
    assert len(app.success) == 1
    assert app.metric[0].value == "€200.00"
    assert app.metric[2].value == "€105.00"
    rows = app.dataframe[0].value
    assert rows["id"].tolist() == ["1", "2"]
    assert rows["health_status"].tolist() == ["🟢 On Track", "🟡 Near Capacity"]


def test_budget_screen_displays_overspend_without_infinite_zero_budget_percentage(database):
    create_project_service(database).create_project(
        name="No budget", planned_budget=0, actual_budget=5
    )
    report = create_budget_service(database).get_report()
    assert budget_frame(report).iloc[0]["burn_rate_pct"] is None
    app = render_budget(database)
    assert not app.exception
    assert "€5.00" in app.warning[0].value
    assert app.dataframe[0].value["burn_rate_pct"].isna().all()
    assert app.dataframe[0].value["health_status"].tolist() == ["🔴 Over Budget"]


def test_budget_screen_handles_empty_database_and_safe_read_errors(database, tmp_path):
    empty = render_budget(database)
    assert not empty.exception
    assert empty.info and not empty.metric
    failed = render_budget(str(tmp_path / "missing-dir" / "private.db"))
    assert not failed.exception
    assert failed.error and not failed.metric
    assert "private.db" not in failed.error[0].value
