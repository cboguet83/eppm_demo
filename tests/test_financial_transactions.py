"""Exact transaction validation and historical euro conversion rules."""

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, localcontext

import pytest

from app.domain.financial_transactions import (
    FinancialRecordType, FinancialTransactionInput, converted_amount, normalize_transaction,
)


def transaction(**changes):
    return replace(FinancialTransactionInput(
        project_id=1, fiscal_year=2026, amount=Decimal('100.01'), currency='EUR',
        exchange_rate=Decimal('1'), financial_record_type=FinancialRecordType.COMMITMENT,
        spending_type='WBS', wbs='UNREGISTERED-WBS'), **changes)


@pytest.mark.parametrize(('field', 'value'), [
    ('project_id', None), ('project_id', True), ('project_id', 0), ('project_id', 2**63),
    ('fiscal_year', None), ('fiscal_year', True), ('fiscal_year', 10000), ('fiscal_year', 0),
    ('amount', None), ('amount', 1.2), ('amount', Decimal('NaN')), ('amount', Decimal('Infinity')),
    ('amount', Decimal('1.001')), ('amount', Decimal('1E1000000')),
    ('exchange_rate', None), ('exchange_rate', 1.0), ('exchange_rate', Decimal('-1')),
    ('exchange_rate', Decimal('0')), ('exchange_rate', Decimal('1.00000000001')),
    ('currency', None), ('currency', ''), ('currency', 'EU'), ('currency', '€UR'),
    ('financial_record_type', None), ('financial_record_type', 'DRAFT'),
    ('spending_type', None), ('spending_type', ''), ('spending_type', '  '),
    ('wbs', None), ('wbs', ''), ('wbs', '\t '), ('wbs', 'bad\x00value'),
    ('source_transaction_id', 0), ('source_transaction_id', True),
    ('accounting_date', '2026-01-01'), ('accounting_date', datetime(2026, 1, 1)),
    ('description', 1), ('counterparty', '\x00'), ('invoice_number', 1),
    ('order_position_number', 1), ('order_number', 1),
])
def test_invalid_transaction_field_is_identified(field, value):
    with pytest.raises(ValueError, match=field):
        normalize_transaction(transaction(**{field: value}))


def test_free_classifications_unknown_wbs_and_currency_normalization():
    value = normalize_transaction(transaction(currency=' usd ', spending_type=' Future classification ',
        wbs=' not in catalog / arbitrary code ', financial_record_type='ACTUAL',
        accounting_date=date(2025, 12, 31)))
    assert value.currency == 'USD'
    assert value.wbs == 'not in catalog / arbitrary code'
    assert value.spending_type == 'Future classification'
    assert value.financial_record_type is FinancialRecordType.ACTUAL
    assert value.fiscal_year == 2026  # Accounting date does not select the fiscal year.


@pytest.mark.parametrize(('amount', 'rate', 'expected'), [
    ('100.01', '0.9234567891', '92.35'), ('1.01', '0.5', '0.50'),
    ('1.03', '0.5', '0.52'), ('-1.03', '0.5', '-0.52'), ('0', '1', '0.00'),
    ('92233720368547758.07', '1', '92233720368547758.07'),
])
def test_conversion_is_exact_and_independent_of_ambient_precision(amount, rate, expected):
    with localcontext(prec=4):
        value = normalize_transaction(transaction(amount=Decimal(amount), exchange_rate=Decimal(rate)))
        assert converted_amount(value.amount, value.exchange_rate) == Decimal(expected)


def test_converted_amount_overflow_is_rejected():
    with pytest.raises(ValueError, match='amount_base_currency'):
        converted_amount(Decimal('92233720368547758.07'), Decimal('2'))


def test_invalid_input_object_is_rejected():
    with pytest.raises(ValueError, match='input'):
        normalize_transaction(None)


@pytest.mark.parametrize('rate', ['0', '-1'])
def test_conversion_rejects_nonpositive_exchange_rates(rate):
    with pytest.raises(ValueError, match='exchange_rate'):
        converted_amount(Decimal('1'), Decimal(rate))
