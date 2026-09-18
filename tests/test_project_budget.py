"""Template cell validation preserves Decimal precision and readonly boundaries."""

from decimal import Decimal

import pytest

from app.domain.project_budget import ProjectBudgetRow, ProjectBudgetView, parse_budget_edits


def view():
    return ProjectBudgetView(1, tuple(ProjectBudgetRow('A', kind, '1', {})
        for kind in ('Approved', 'Proposed', 'LIVE_BUDGET', 'ACTUAL', 'COMMITMENT')), 'revision', True)


def cell(**changes):
    return {'wbs': 'A', 'kind': 'LIVE_BUDGET', 'year': 2026, 'amount': '123.45'} | changes


@pytest.mark.parametrize('payload', [None, [], {}, [cell(kind='Approved')], [cell(kind='Proposed')],
    [cell(kind='FUTURE')], [cell(wbs='Hidden')], [cell(year=True)], [cell(year=1990)],
    [cell(amount=1.2)], [cell(amount='1.001')], [cell(amount='NaN')], [cell(amount='1e2')],
    [cell(amount='-1')], [cell(amount='99999999999999999999')], [cell(), cell()],
    [cell() | {'project_id': 2}], [False], [cell(kind=[])], [cell(wbs=[])],
])
def test_invalid_or_readonly_budget_cells_are_rejected(payload):
    with pytest.raises(ValueError):
        parse_budget_edits(payload, view(), range(2025, 2035))


def test_exact_cell_amounts_blank_and_signed_adjustments():
    values = parse_budget_edits([cell(amount='123,45'), cell(kind='ACTUAL', amount='-10.25'),
                                cell(kind='COMMITMENT', amount='')], view(), range(2025, 2035))
    assert [value.amount for value in values] == [Decimal('123.45'), Decimal('-10.25'), None]
