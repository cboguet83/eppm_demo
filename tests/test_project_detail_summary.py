"""Project summary uses annual financials and explains the variance sign."""

from contextlib import nullcontext
from decimal import Decimal

import pandas as pd

from app.presentation.pages import portfolio


def test_summary_renders_annual_budget_before_spending_and_variance_tooltip(monkeypatch):
    rendered = []
    monkeypatch.setattr(portfolio.st, 'columns', lambda *args: [nullcontext(), nullcontext()])
    monkeypatch.setattr(portfolio.st, 'container', lambda **kwargs: nullcontext())
    monkeypatch.setattr(portfolio.st, 'subheader', lambda *args: None)
    monkeypatch.setattr(portfolio.st, 'html', rendered.append)
    monkeypatch.setattr(portfolio, '_render_project_edit_action', lambda *args: None)
    monkeypatch.setattr(portfolio, '_render_project_detail_sections', lambda *args: None)
    portfolio._draw_project_details(pd.Series({
        'id': 1, 'name': 'Example', 'financial_year': 2026,
        'current_year_approved': Decimal('100'), 'current_year_actual': Decimal('25'),
        'current_year_commitment': Decimal('80'), 'actual_budget': Decimal('9999'),
    }), None)
    markup = rendered[0]
    assert markup.index('Approved budget (2026)') < markup.index('Actual (2026)') < markup.index('Commitment (2026)')
    assert '€100.00' in markup and '€25.00' in markup and '€80.00' in markup
    assert '€5.00' in markup and '9,999' not in markup
    assert 'title="Variance (2026) = Actual (2026) + Commitment (2026) − Approved budget (2026).' in markup
    assert 'Positive means over budget; negative means under budget.' in markup
