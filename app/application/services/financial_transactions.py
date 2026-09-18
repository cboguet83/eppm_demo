"""Project financial transaction CRUD and yearly historical euro reporting."""

from collections.abc import Collection

from app.application.ports.financial_transactions import FinancialTransactionGateway, FinancialTransactionStore
from app.domain.financial_transactions import (
    FinancialTransaction, FinancialTransactionInput, YearlyProjectFinancials,
    converted_amount, normalize_transaction, validate_identifier,
)


class FinancialTransactionService:
    """Keep commitments separate from actuals and use stored conversion values."""

    def __init__(self, gateway: FinancialTransactionGateway) -> None:
        """Inject an authorized, transaction-bound persistence gateway."""
        self.gateway = gateway

    def create(self, value: FinancialTransactionInput) -> int:
        """Create one record without changing any linked source commitment."""
        value = normalize_transaction(value)
        amount = converted_amount(value.amount, value.exchange_rate)

        def operation(store: FinancialTransactionStore) -> int:
            if value.source_transaction_id is not None:
                store.require_source(value.source_transaction_id)
            return store.create(value, amount)

        return self.gateway.run(operation, write=True, project_ids=(value.project_id,))

    def get(self, project_id: int, transaction_id: int) -> FinancialTransaction | None:
        """Read one record in an explicitly authorized project."""
        validate_identifier(project_id, 'project_id')
        validate_identifier(transaction_id, 'id')
        return self.gateway.run(lambda store: store.get(project_id, transaction_id), project_ids=(project_id,))

    def list(self, project_id: int, fiscal_year: int | None = None) -> tuple[FinancialTransaction, ...]:
        """Read project records, optionally narrowed to a fiscal year."""
        validate_identifier(project_id, 'project_id')
        if fiscal_year is not None and (type(fiscal_year) is not int or not 1 <= fiscal_year <= 9999):
            raise ValueError('fiscal_year must be an integer between 1 and 9999.')
        return self.gateway.run(lambda store: store.list(project_id, fiscal_year), project_ids=(project_id,))

    def update(self, transaction_id: int, value: FinancialTransactionInput) -> bool:
        """Correct a record in its project without converting a commitment to an actual.

        Metadata-only corrections retain the stored euro value. Explicit amount or
        rate corrections recalculate only this record; sources remain untouched.
        """
        validate_identifier(transaction_id, 'id')
        value = normalize_transaction(value)

        def operation(store: FinancialTransactionStore) -> bool:
            current = store.get(value.project_id, transaction_id)
            if current is None:
                return False
            if current.financial_record_type != value.financial_record_type:
                raise ValueError('financial_record_type cannot change. Create a separate transaction instead.')
            if value.source_transaction_id is not None:
                store.require_source(value.source_transaction_id)
            amount = current.amount_base_currency
            if (value.amount, value.exchange_rate) != (current.amount, current.exchange_rate):
                amount = converted_amount(value.amount, value.exchange_rate)
            return store.update(transaction_id, value, amount)

        return self.gateway.run(operation, write=True, project_ids=(value.project_id,))

    def delete(self, project_id: int, transaction_id: int) -> bool:
        """Delete an unreferenced record; linked source records remain protected."""
        validate_identifier(project_id, 'project_id')
        validate_identifier(transaction_id, 'id')
        return self.gateway.run(lambda store: store.delete(project_id, transaction_id),
                                write=True, project_ids=(project_id,))

    def yearly_totals(self, project_ids: Collection[int] | None = None) -> tuple[YearlyProjectFinancials, ...]:
        """Sum stored euro amounts by accessible project, year and record type.

        None selects the caller's readable projects; an empty collection selects
        none. Years without records are omitted. Commitments are original totals.
        """
        identities = None if project_ids is None else tuple(set(project_ids))
        if identities is not None:
            for identity in identities:
                validate_identifier(identity, 'project_id')
        return self.gateway.run(lambda store: store.yearly_totals(identities))
