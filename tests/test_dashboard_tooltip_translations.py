"""Dashboard help and chart labels follow every supported session language."""

from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace

import pytest

from app.presentation.components.dashboard_resource_chart import finance_chart
from app.presentation.i18n import SUPPORTED_LOCALES, load_locale_catalog, set_current_locale, t
from app.presentation.pages import dashboard


@pytest.mark.parametrize('locale', SUPPORTED_LOCALES)
def test_financial_chart_payload_and_card_help_follow_language(monkeypatch, locale):
    payloads, metrics = [], []
    monkeypatch.setattr(dashboard.st.components.v2, 'component',
                        lambda *args, **kwargs: lambda **values: payloads.append(values['data']))
    monkeypatch.setattr(dashboard.st, 'container', lambda **kwargs: nullcontext())
    monkeypatch.setattr(dashboard.st, 'metric', lambda *args, **kwargs: metrics.append((args, kwargs)))
    monkeypatch.setattr(dashboard, 'financial_utilization', lambda *args:
                        SimpleNamespace(actual_percentage=None, committed_percentage=None))
    catalog = load_locale_catalog(locale)['dashboard']
    try:
        for selected in ('en', locale):
            set_current_locale(selected)
            finance_chart(series=[], transactions=[], today='2026-09-19', year=2026,
                          locale=selected, title='Finance', value_label='EUR')
        assert [row['name'] for row in payloads[-1]['transactionSeries']] == [catalog['actual'], catalog['commitment']]
        dashboard._financial_indicators(SimpleNamespace(today=lambda: date(2026, 9, 19)),
                                        SimpleNamespace(budget=None, financials=None))
        assert metrics[0][0] == (catalog['actual_ratio'], catalog['not_available'])
        assert metrics[1][0][0] == catalog['committed_ratio']
        assert metrics[0][1]['help'] == catalog['financial_help'].format(start=2024, end=2035)
        assert t('dashboard.late_help') == catalog['late_help']
        assert t('dashboard.issue_count', count=3) != 'dashboard.issue_count'
        assert t('organization_filters.multiselect_hint') == load_locale_catalog(locale)['organization_filters']['multiselect_hint']
    finally:
        set_current_locale('en')
