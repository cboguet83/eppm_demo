"""Project financial records with historical Decimal amounts in euros."""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from enum import StrEnum
import re

from app.domain.finance import MAX_AMOUNT

BASE_CURRENCY = 'EUR'
CENT = Decimal('0.01')
RATE_UNIT = Decimal('0.0000000001')
MAX_RATE = Decimal('999999999999999999.9999999999')


class FinancialRecordType(StrEnum):
    """Stable accounting codes, independent of future translated UI labels."""

    COMMITMENT = 'COMMITMENT'
    ACTUAL = 'ACTUAL'
    LIVE_BUDGET = 'LIVE_BUDGET'


PROJECT_EDITOR_RECORD_TYPES = frozenset({FinancialRecordType.COMMITMENT, FinancialRecordType.ACTUAL, FinancialRecordType.LIVE_BUDGET})


@dataclass(frozen=True, kw_only=True)
class FinancialTransactionInput:
    """Caller-supplied fields; base currency amounts are calculated by the service.

    Exchange rates express euros per one unit of transaction currency. Updating
    amount or rate explicitly corrects this record's conversion, never its source.
    """

    project_id: int
    fiscal_year: int
    amount: Decimal
    currency: str
    exchange_rate: Decimal
    financial_record_type: FinancialRecordType
    spending_type: str
    wbs: str
    accounting_date: date | None = None
    description: str | None = None
    counterparty: str | None = None
    invoice_number: str | None = None
    order_position_number: str | None = None
    order_number: str | None = None
    source_transaction_id: int | None = None


@dataclass(frozen=True, kw_only=True)
class FinancialTransaction(FinancialTransactionInput):
    """Persisted transaction including its generated ID and historical conversion."""

    id: int
    amount_base_currency: Decimal


@dataclass(frozen=True)
class YearlyProjectFinancials:
    """Euro totals for one project and fiscal year; commitments are not netted."""

    project_id: int
    fiscal_year: int
    total_actual_spending: Decimal
    total_commitment: Decimal


def validate_identifier(value: int, field: str) -> None:
    """Validate an identity without allowing bools or overflowing PostgreSQL bigint."""
    if type(value) is not int or not 1 <= value <= 9223372036854775807:
        raise ValueError(f'{field} must be a positive integer ID.')


def _decimal(value: Decimal, field: str, unit: Decimal, maximum: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f'{field} must be a finite Decimal value.')
    if value.copy_abs() > maximum or value != value.quantize(unit):
        raise ValueError(f'{field} exceeds the supported range or decimal precision.')


def normalize_transaction(value: FinancialTransactionInput) -> FinancialTransactionInput:
    """Validate mandatory data without interpreting spending classifications or WBS."""
    if not isinstance(value, FinancialTransactionInput):
        raise ValueError('Provide financial transaction input.')
    validate_identifier(value.project_id, 'project_id')
    if type(value.fiscal_year) is not int or not 1 <= value.fiscal_year <= 9999:
        raise ValueError('fiscal_year must be an integer between 1 and 9999.')
    if value.source_transaction_id is not None:
        validate_identifier(value.source_transaction_id, 'source_transaction_id')
    if not isinstance(value.currency, str) or not re.fullmatch('[A-Za-z]{3}', value.currency.strip()):
        raise ValueError('currency must be a three-letter currency code.')
    for field in ('wbs', 'spending_type'):
        text = getattr(value, field)
        if not isinstance(text, str) or not text.strip() or '\x00' in text:
            raise ValueError(f'{field} is required and must be nonempty text.')
    for field in ('description', 'counterparty', 'invoice_number', 'order_position_number', 'order_number'):
        text = getattr(value, field)
        if text is not None and (not isinstance(text, str) or '\x00' in text):
            raise ValueError(f'{field} must be text or null.')
    if value.accounting_date is not None and type(value.accounting_date) is not date:
        raise ValueError('accounting_date must be a date or null.')
    try:
        record_type = FinancialRecordType(value.financial_record_type)
    except (ValueError, TypeError):
        raise ValueError('financial_record_type must be COMMITMENT, ACTUAL or LIVE_BUDGET.') from None
    with localcontext(prec=60, rounding=ROUND_HALF_EVEN):
        _decimal(value.amount, 'amount', CENT, MAX_AMOUNT)
        _decimal(value.exchange_rate, 'exchange_rate', RATE_UNIT, MAX_RATE)
        if record_type == FinancialRecordType.LIVE_BUDGET and value.amount < 0:
            raise ValueError('Live budget amounts must be nonnegative.')
        if value.exchange_rate <= 0:
            raise ValueError('exchange_rate must be greater than zero.')
    return replace(value, currency=value.currency.strip().upper(),
                   wbs=value.wbs.strip(), spending_type=value.spending_type.strip(),
                   financial_record_type=record_type)


def converted_amount(amount: Decimal, exchange_rate: Decimal) -> Decimal:
    """Convert using the supplied historical rate, rounding euro cents half-even."""
    with localcontext(prec=60, rounding=ROUND_HALF_EVEN):
        _decimal(amount, 'amount', CENT, MAX_AMOUNT)
        _decimal(exchange_rate, 'exchange_rate', RATE_UNIT, MAX_RATE)
        if exchange_rate <= 0:
            raise ValueError('exchange_rate must be greater than zero.')
        result = (amount * exchange_rate).quantize(CENT)
        _decimal(result, 'amount_base_currency', CENT, MAX_AMOUNT)
        return result
