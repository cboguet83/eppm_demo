"""Real PostgreSQL CRUD, financial history and project authorization boundaries."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext
from types import SimpleNamespace

import psycopg
import pytest

from app.application.exceptions import FinanceStorageError
from app.application.services.financial_transactions import FinancialTransactionService
from app.domain.access.models import AccessDenied
from app.domain.financial_transactions import FinancialRecordType, YearlyProjectFinancials
from app.infrastructure.postgresql.financial_transactions import PostgresFinancialTransactionGateway
from app.main import create_financial_transaction_service
from tests.test_financial_transactions import transaction


def gateway(authorized, user_id=4):
    return PostgresFinancialTransactionGateway(authorized.database, authorized.key, access=authorized.binding(user_id).access)


def service(authorized, user_id=4):
    return FinancialTransactionService(gateway(authorized, user_id))


def test_commitment_multiple_actuals_and_unlinked_actual_remain_separate(authorized):
    finance = service(authorized)
    commitment = finance.create(transaction(amount=Decimal('100000')))
    first = finance.create(transaction(amount=Decimal('25000'), financial_record_type=FinancialRecordType.ACTUAL,
                                        source_transaction_id=commitment))
    second = finance.create(transaction(amount=Decimal('30000'), financial_record_type=FinancialRecordType.ACTUAL,
                                         source_transaction_id=commitment))
    unlinked = finance.create(transaction(project_id=2, financial_record_type=FinancialRecordType.ACTUAL))
    assert finance.get(1, commitment).amount_base_currency == Decimal('100000.00')
    assert finance.get(1, first).source_transaction_id == finance.get(1, second).source_transaction_id == commitment
    assert finance.get(2, unlinked).source_transaction_id is None
    assert finance.yearly_totals([1]) == (YearlyProjectFinancials(1, 2026, Decimal('55000.00'), Decimal('100000.00')),)
    assert [row.id for row in finance.list(1, 2026)] == [commitment, first, second]
    assert finance.list(1, 2025) == ()


def test_yearly_totals_use_stored_conversion_and_separate_projects_and_years(authorized):
    finance = service(authorized)
    for project, year, kind, amount, rate in [
        (1, 2026, 'ACTUAL', '1.03', '.5'), (1, 2026, 'ACTUAL', '1.03', '.5'),
        (1, 2026, 'COMMITMENT', '100', '1.5'), (1, 2027, 'ACTUAL', '10', '2'),
        (2, 2026, 'ACTUAL', '50', '1'), (3, 2026, 'COMMITMENT', '20', '1'),
    ]:
        finance.create(transaction(project_id=project, fiscal_year=year, financial_record_type=kind,
            amount=Decimal(amount), currency='USD', exchange_rate=Decimal(rate)))
    with localcontext(prec=4):
        assert finance.yearly_totals([2, 1, 1]) == (
            YearlyProjectFinancials(1, 2026, Decimal('1.04'), Decimal('150.00')),
            YearlyProjectFinancials(1, 2027, Decimal('20.00'), Decimal('0')),
            YearlyProjectFinancials(2, 2026, Decimal('50.00'), Decimal('0')))
    assert finance.yearly_totals([]) == ()
    assert finance.yearly_totals([999]) == ()
    assert len(finance.yearly_totals()) == 4


def test_update_metadata_and_rate_corrections_do_not_mutate_other_records(authorized):
    finance = service(authorized)
    original = transaction(currency='USD', amount=Decimal('100.01'), exchange_rate=Decimal('.9234567891'),
        accounting_date=date(2025, 12, 31), counterparty='Supplier', invoice_number='0001',
        order_position_number='0010', order_number='0002', description='Original')
    identity = finance.create(original)
    actual = finance.create(replace(original, financial_record_type=FinancialRecordType.ACTUAL, source_transaction_id=identity))
    record = finance.get(1, identity)
    assert record.amount_base_currency == Decimal('92.35') and record.wbs == 'UNREGISTERED-WBS'
    assert finance.update(identity, replace(original, description='Corrected'))
    assert finance.get(1, identity).amount_base_currency == record.amount_base_currency
    assert finance.update(actual, replace(original, exchange_rate=Decimal('1.1'),
        financial_record_type=FinancialRecordType.ACTUAL, source_transaction_id=identity))
    assert finance.get(1, actual).amount_base_currency == Decimal('110.01')
    assert finance.get(1, identity).amount_base_currency == Decimal('92.35')
    with pytest.raises(ValueError, match='cannot change'):
        finance.update(identity, replace(original, financial_record_type=FinancialRecordType.ACTUAL))
    assert finance.get(1, identity).financial_record_type is FinancialRecordType.COMMITMENT
    assert not finance.update(identity, replace(original, project_id=2))
    assert not finance.update(9999, original)
    assert finance.get(1, 9999) is None


def test_delete_protects_source_and_rolls_back_rejected_change(authorized):
    finance = service(authorized)
    source = finance.create(transaction())
    actual = finance.create(transaction(financial_record_type=FinancialRecordType.ACTUAL, source_transaction_id=source))
    with pytest.raises(ValueError, match='cannot be deleted'):
        finance.delete(1, source)
    assert len(finance.list(1)) == 2
    assert finance.delete(1, actual) and finance.delete(1, source)
    assert not finance.delete(1, source)
    assert finance.yearly_totals() == ()


def test_unknown_source_and_project_are_rejected_without_partial_insert(authorized):
    finance = service(authorized)
    for value in (transaction(source_transaction_id=9999), transaction(project_id=9999)):
        with pytest.raises(AccessDenied):
            finance.create(value)
    assert finance.list(1) == ()


def test_reads_totals_and_finance_writes_respect_project_scope(authorized):
    finance = service(authorized)
    one = finance.create(transaction())
    hidden = finance.create(transaction(project_id=3))
    scoped = service(authorized, 1)
    assert scoped.get(1, one) and len(scoped.yearly_totals([1, 3])) == 1
    assert {row.project_id for row in scoped.yearly_totals()} == {1}
    with pytest.raises(AccessDenied):
        scoped.get(3, hidden)
    read_only = finance.create(transaction(project_id=2))
    for operation in (lambda: scoped.create(transaction(project_id=2)),
                      lambda: scoped.update(read_only, transaction(project_id=2)),
                      lambda: scoped.delete(2, read_only)):
        with pytest.raises(AccessDenied):
            operation()
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
            VALUES (1,'finance_editor','{"kind":"all"}',900,'test setup'),
                   (3,'finance_editor','{"kind":"all"}',900,'test setup')""")
    assert scoped.create(transaction(project_id=2))  # Finance + read, project edit is not required.
    for project in (1, 3):
        with pytest.raises(AccessDenied):
            service(authorized, 3).create(transaction(project_id=project))
    with pytest.raises(AccessDenied):
        scoped.create(transaction(source_transaction_id=hidden))
    with pytest.raises(AccessDenied):
        scoped.create(transaction(project_id=3))
    assert scoped.update(one, transaction(description='Allowed'))
    assert scoped.delete(1, one)


def test_raw_runtime_sql_cannot_bypass_project_finance_or_type_permissions(authorized):
    finance = service(authorized)
    identity = finance.create(transaction())
    finance.create(transaction(project_id=3))
    assert authorized.query('SELECT project_id FROM eppm.project_financial_transaction', user_id=1) == [(1,)]
    assert authorized.query('SELECT id FROM eppm.project_financial_transaction', user_id=3) == []
    assert authorized.query('UPDATE eppm.project_financial_transaction SET amount=0 RETURNING id', user_id=2, write=True) == []
    assert authorized.query('DELETE FROM eppm.project_financial_transaction RETURNING id', user_id=2, write=True) == []
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query("UPDATE eppm.project_financial_transaction SET financial_record_type='ACTUAL' WHERE id=%s",
                         (identity,), user_id=4, write=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query("""INSERT INTO eppm.project_financial_transaction
            (project_id,fiscal_year,amount,currency,exchange_rate,amount_base_currency,financial_record_type,spending_type,wbs)
            VALUES (2,2026,1,'EUR',1,1,'ACTUAL','Anything','WBS')""", user_id=1, write=True)


def test_disabled_account_is_rechecked(authorized):
    finance = service(authorized)
    identity = finance.create(transaction())
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.app_user SET status='disabled' WHERE id=4")
    for operation in (lambda: finance.get(1, identity), lambda: finance.yearly_totals(),
                      lambda: finance.create(transaction()), lambda: finance.delete(1, identity)):
        with pytest.raises(AccessDenied):
            operation()


def test_parallel_actuals_preserve_commitment_and_exact_totals(authorized):
    finance = service(authorized)
    source = finance.create(transaction(amount=Decimal('100000')))
    value = transaction(amount=Decimal('25000'), financial_record_type=FinancialRecordType.ACTUAL, source_transaction_id=source)
    with ThreadPoolExecutor(max_workers=2) as executor:
        identities = list(executor.map(finance.create, [value, value]))
    assert len(set(identities)) == 2
    assert finance.yearly_totals([1]) == (YearlyProjectFinancials(1, 2026, Decimal('50000.00'), Decimal('100000.00')),)


def test_composition_factory_and_readonly_store(authorized):
    resources = SimpleNamespace(database=authorized.database, key=authorized.key)
    finance = create_financial_transaction_service(resources, access=authorized.binding(4).access)
    assert finance.create(transaction())
    with pytest.raises(FinanceStorageError, match='writer'):
        gateway(authorized).run(lambda store: store.create(transaction(), Decimal('100.01')))


def test_finance_permission_revocation_blocks_existing_service_writes(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
            VALUES (1,'finance_editor','{"kind":"all"}',900,'test setup')""")
    finance = service(authorized, 1)
    identity = finance.create(transaction(project_id=2))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("DELETE FROM eppm.app_role_assignment WHERE user_id=1 AND role='finance_editor'")
    assert finance.get(2, identity)
    with pytest.raises(AccessDenied):
        finance.update(identity, transaction(project_id=2, amount=Decimal('50')))
    assert finance.get(2, identity).amount == Decimal('100.01')


@pytest.mark.parametrize('record_type', ['COMMITMENT', 'ACTUAL', 'LIVE_BUDGET'])
def test_project_editor_crud_is_allowed_only_on_editable_projects(authorized, record_type):
    finance = service(authorized, 1)
    value = transaction(financial_record_type=record_type)
    identity = finance.create(value)
    assert finance.update(identity, replace(value, description='Scoped correction'))
    assert finance.get(1, identity).description == 'Scoped correction'
    assert finance.delete(1, identity)
    for project_id in (2, 3):
        with pytest.raises(AccessDenied):
            finance.create(replace(value, project_id=project_id))


def test_new_record_types_do_not_implicitly_grant_project_editor_writes(authorized):
    # Simulate a future schema adding a type without changing the authorization
    # allowlists. Use the repository boundary so today's input enum is not involved.
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('ALTER TABLE eppm.project_financial_transaction DROP CONSTRAINT project_financial_transaction_financial_record_type_check')
        connection.execute("""ALTER TABLE eppm.project_financial_transaction ADD CHECK
            (financial_record_type IN ('COMMITMENT','ACTUAL','LIVE_BUDGET','FUTURE'))""")
    value = transaction(financial_record_type='FUTURE')
    with pytest.raises(AccessDenied, match='only COMMITMENT, ACTUAL and LIVE_BUDGET'):
        gateway(authorized, 1).run(lambda store: store.create(value, Decimal('100.01')),
                                 write=True, project_ids=(1,))
    statement = """INSERT INTO eppm.project_financial_transaction
        (project_id,fiscal_year,amount,currency,exchange_rate,amount_base_currency,financial_record_type,spending_type,wbs)
        VALUES (1,2026,1,'EUR',1,1,'FUTURE','Anything','WBS') RETURNING id"""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query(statement, user_id=1, write=True)
    identity = authorized.query(statement, user_id=4, write=True)[0][0]
    assert authorized.query('UPDATE eppm.project_financial_transaction SET amount=2 WHERE id=%s RETURNING id',
                            (identity,), user_id=1, write=True) == []
    assert authorized.query('DELETE FROM eppm.project_financial_transaction WHERE id=%s RETURNING id',
                            (identity,), user_id=1, write=True) == []
    assert authorized.query('UPDATE eppm.project_financial_transaction SET amount=2 WHERE id=%s RETURNING id',
                            (identity,), user_id=4, write=True) == [(identity,)]


def test_failed_reference_update_is_atomic_and_optional_source_rules_are_not_added(authorized):
    finance = service(authorized)
    source = finance.create(transaction(project_id=2, financial_record_type=FinancialRecordType.ACTUAL))
    identity = finance.create(transaction(source_transaction_id=source))
    before = finance.get(1, identity)
    with pytest.raises(AccessDenied):
        finance.update(identity, transaction(source_transaction_id=9999, description='Not committed'))
    assert finance.get(1, identity) == before


def test_public_query_and_mutation_boundaries_reject_invalid_identifiers(authorized):
    finance = service(authorized)
    for operation in (lambda: finance.get(True, 1), lambda: finance.get(1, 0),
                      lambda: finance.list(1, 0), lambda: finance.list(1, True),
                      lambda: finance.update(0, transaction()), lambda: finance.delete(1, 0),
                      lambda: finance.yearly_totals([True])):
        with pytest.raises(ValueError):
            operation()


def test_unexpected_storage_failure_exposes_no_database_details(authorized, caplog):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('DROP TABLE eppm.project_financial_transaction')
    with pytest.raises(FinanceStorageError) as caught:
        service(authorized).yearly_totals()
    assert 'SELECT' not in str(caught.value) and 'project_financial_transaction' not in str(caught.value)
    assert 'UndefinedTable' in caplog.text
