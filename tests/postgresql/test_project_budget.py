"""Project-scoped live budget editing and immutable accounting corrections."""

from datetime import date
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace

import psycopg
import pytest

from app.domain.access.models import AccessDenied
from app.main import create_project_budget_service
from tests.postgresql.test_financial_transactions import service as transaction_service
from tests.test_financial_transactions import transaction


def budget(authorized, user_id=4):
    service = create_project_budget_service(SimpleNamespace(database=authorized.database, key=authorized.key),
                                            access=authorized.binding(user_id).access)
    service.today = lambda: date(2026, 6, 1)
    return service


def cell(kind='LIVE_BUDGET', amount='123.45', year=2026):
    return dict(wbs='A', kind=kind, year=year, amount=amount)


@pytest.fixture
def mapped_wbs(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.wbs(id,code) VALUES(1,'A')")
        connection.execute('INSERT INTO eppm.project_wbs VALUES(1,1,50)')
    return authorized


@pytest.mark.parametrize('user_id', [1, 4])
def test_project_editor_and_business_admin_edit_live_budget_without_revisions(mapped_wbs, user_id):
    service = budget(mapped_wbs, user_id)
    initial = service.view(1)
    assert initial.can_edit and len(initial.rows) == 5
    assert service.save(1, initial.revision, [cell()])
    finance = transaction_service(mapped_wbs)
    record, = finance.list(1)
    assert record.amount_base_currency == Decimal('123.45')  # no WBS-share rescaling
    assert record.financial_record_type == 'LIVE_BUDGET'
    assert finance.yearly_totals([1]) == ()
    assert service.save(1, service.view(1).revision, [cell(amount='200')])
    updated, = finance.list(1)
    assert updated.id == record.id and updated.amount == Decimal('200')
    assert service.view(1).rows[2].version == ''
    assert not service.save(1, service.view(1).revision, [cell(amount='200')])
    assert service.save(1, service.view(1).revision, [cell(amount='')])
    assert finance.list(1) == ()


def test_adjustments_preserve_original_actual_and_commitment_transactions(mapped_wbs):
    finance = transaction_service(mapped_wbs)
    commitment = finance.create(transaction(wbs='A', amount=Decimal('100')))
    actual = finance.create(transaction(wbs='A', amount=Decimal('20'),
                                        financial_record_type='ACTUAL', source_transaction_id=commitment))
    service = budget(mapped_wbs, 1)
    assert service.save(1, service.view(1).revision,
                        [cell('COMMITMENT', '150'), cell('ACTUAL', '40'), cell(amount='250')])
    assert finance.get(1, actual).amount == Decimal('20')
    assert finance.get(1, actual).source_transaction_id == commitment
    assert finance.get(1, commitment).amount == Decimal('100')
    totals, = finance.yearly_totals([1])
    assert (totals.total_actual_spending, totals.total_commitment) == (Decimal('40'), Decimal('150'))
    service.save(1, service.view(1).revision, [cell('ACTUAL', '')])
    assert finance.yearly_totals([1])[0].total_actual_spending == 0


def test_stale_or_invalid_table_save_is_atomic(mapped_wbs):
    service = budget(mapped_wbs)
    old = service.view(1)
    service.save(1, old.revision, [cell()])
    with pytest.raises(ValueError, match='changed since'):
        service.save(1, old.revision, [cell('ACTUAL', '50')])
    with pytest.raises(ValueError, match='Only'):
        service.save(1, service.view(1).revision, [cell(amount='900'), cell('Approved', '1')])
    assert transaction_service(mapped_wbs).list(1)[0].amount == Decimal('123.45')
    assert len(transaction_service(mapped_wbs).list(1)) == 1


def test_readonly_scope_cannot_edit_or_read_hidden_project(mapped_wbs):
    editor = budget(mapped_wbs, 1)
    assert not editor.view(2).can_edit
    with pytest.raises(AccessDenied):
        editor.save(2, editor.view(2).revision, [cell()])
    with pytest.raises(AccessDenied):
        editor.view(3)


def test_live_budget_uniqueness_and_nonnegative_values_are_enforced(mapped_wbs):
    finance = transaction_service(mapped_wbs, 1)
    value = transaction(wbs='A', financial_record_type='LIVE_BUDGET')
    finance.create(value)
    with pytest.raises(ValueError):
        finance.create(value)
    with pytest.raises(ValueError, match='nonnegative'):
        finance.create(transaction(wbs='B', financial_record_type='LIVE_BUDGET', amount=Decimal('-1')))
    finance.create(transaction(wbs='B', financial_record_type='LIVE_BUDGET', amount=Decimal('0')))
    assert [row.wbs for row in budget(mapped_wbs).view(1).rows[::5]] == ['A', 'B']
    with psycopg.connect(mapped_wbs.setup.operator_url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute("UPDATE eppm.project_financial_transaction SET amount=-1 WHERE financial_record_type='LIVE_BUDGET'")


def test_simultaneous_edits_cannot_overwrite_each_other(mapped_wbs):
    service = budget(mapped_wbs)
    initial = service.view(1)

    def save(amount):
        try:
            return service.save(1, initial.revision, [cell(amount=amount)])
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, ['200', '300']))
    assert sorted(results) == [False, True]
    records = transaction_service(mapped_wbs).list(1)
    assert len(records) == 1 and records[0].amount in {Decimal(200), Decimal(300)}


def test_failed_adjustment_rolls_back_live_budget_change(mapped_wbs):
    from app.domain.finance import MAX_AMOUNT

    finance = transaction_service(mapped_wbs)
    finance.create(transaction(wbs='A', financial_record_type='ACTUAL', amount=-MAX_AMOUNT))
    service = budget(mapped_wbs)
    before = service.view(1)
    with pytest.raises(ValueError, match='supported range'):
        service.save(1, before.revision, [cell(), cell('ACTUAL', str(MAX_AMOUNT))])
    assert service.view(1).revision == before.revision
    assert len(finance.list(1)) == 1
