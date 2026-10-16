"""Financial dashboard totals follow project scopes, filters and cache revisions."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
import json

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from app.domain.access.models import AccessDenied
from app.main import create_dashboard_service, create_finance_service
from tests.postgresql.test_dashboard_ui import business, screen
from tests.postgresql.ui import runtime
from tests.postgresql.test_financial_transactions import service as financial_service
from tests.test_financial_transactions import transaction


def test_transaction_edits_invalidate_reports_and_hidden_projects_stay_private(business, authorized):
    runtime, _, _, editor, _ = business
    dashboard = create_dashboard_service(runtime, access=editor)
    dashboard.today = lambda: date(2026, 6, 1)
    finance = financial_service(authorized)
    old = dashboard.revision()
    value = transaction(wbs='A', amount=Decimal('20.01'), financial_record_type='ACTUAL')
    identity = finance.create(value)
    changed = dashboard.revision()
    assert changed != old
    assert dashboard.report([1]).financials[0].total_actual_spending == Decimal('20.01')
    finance.update(identity, replace(value, amount=Decimal('30.01')))
    assert dashboard.revision() != changed
    changed = dashboard.revision()
    finance.create(transaction(project_id=2, amount=Decimal('999')))
    finance.create(transaction(financial_record_type='LIVE_BUDGET'))
    assert dashboard.revision() == changed
    assert len(dashboard.report([1]).financials) == 1
    with pytest.raises(AccessDenied):
        dashboard.report([2])
    finance.delete(1, identity)
    assert dashboard.revision() != changed
    assert dashboard.report([1]).financials == ()


def test_dashboard_stacks_and_utilization_follow_status_filters(business, authorized):
    runtime, _, _, _, admin = business
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET status='Completed' WHERE id=2")
        connection.execute("INSERT INTO eppm.wbs(id,code) VALUES(1,'A')")
        connection.execute('INSERT INTO eppm.project_wbs VALUES(1,1,50),(2,1,50)')
    budgets = create_finance_service(runtime, access=admin)
    budgets.today = lambda: date(2026, 6, 1)
    budgets.save([{'code': 'A', 'amounts': {'2026': '200'}}], base_id=None,
                 name='Delivery budget', status='Approved', year=2026)
    finance = financial_service(authorized)
    for project, kind, value in [(1, 'ACTUAL', '20'), (1, 'COMMITMENT', '30'),
                                 (2, 'ACTUAL', '60'), (2, 'COMMITMENT', '40'), (1, 'LIVE_BUDGET', '999')]:
        finance.create(transaction(project_id=project, financial_record_type=kind, amount=Decimal(value)))
    app = AppTest.from_function(screen, args=(runtime, admin.actor), default_timeout=20).run()

    def chart():
        return json.loads(next(item.proto.json for item in app.get('bidi_component')
                               if item.proto.id.endswith('-dashboard_finance_chart')))

    def ratios():
        return {item.label: item.value for item in app.metric if 'Approved Budget' in item.label}

    assert not app.exception and not app.error
    assert chart()['budgetSeries'][0]['name'] == 'Approved — Delivery budget'
    assert not any('Delivery budget' in item.value for item in app.caption)
    assert next(row for row in chart()['transactions'] if row['year'] == 2026) == {
        'year': 2026, 'actual': 20.0, 'commitment': 30.0}
    assert [item['color'] for item in chart()['transactionSeries']] == ['#C41049', '#6D6E70']
    assert ratios() == {'Actual / Approved Budget (2026)': '20.0%', '(Actual + Commitment) / Approved Budget (2026)': '50.0%'}
    app.checkbox(key='dashboard_filter_status_option_Completed').check().run()
    assert next(row for row in chart()['transactions'] if row['year'] == 2026) == {
        'year': 2026, 'actual': 80.0, 'commitment': 70.0}
    assert ratios() == {'Actual / Approved Budget (2026)': '40.0%', '(Actual + Commitment) / Approved Budget (2026)': '75.0%'}
