"""Native Decimal finance history, independent access and complete save replay."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal, localcontext
from threading import Barrier, Event

import psycopg
import pytest

from app.application.exceptions import FinanceStorageError
from app.application.services.finance import FinanceService
from app.domain.access.models import AccessDenied
from app.domain.dashboard import WbsShare, allocated_budget
from app.domain.finance import BudgetRow, FinanceError, MAX_AMOUNT, euro_text, export_csv
from app.infrastructure.postgresql.finance import PostgresFinanceGateway


def gateway(authorized, user_id=4):
    return PostgresFinanceGateway(authorized.database, authorized.key, access=authorized.binding(user_id).access)


def service(authorized, user_id=4, year=2026):
    return FinanceService(gateway(authorized, user_id), lambda: date(year, 6, 1))


def rows(code='A', amount='100.01', year=2026):
    return [{'code': code, 'amounts': {str(year): amount}}]


def save(finance, values=None, *, base_id=None, status='Draft', name='Plan', year=2026):
    return finance.save(rows() if values is None else values, base_id=base_id, status=status, name=name, year=year)


@pytest.fixture
def finance(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.wbs(code,description) VALUES ('A','=Known description'),('B','Second')")
    return service(authorized)


def test_native_finance_round_trips_decimal_euros_blank_zero_and_large_exact_amounts(finance, authorized):
    values = rows(amount='0.10') + rows('B', '0') + rows('#FICTIVE', '') + rows('MAX', str(MAX_AMOUNT))
    first = save(finance, values)
    view = finance.view()
    assert view.selected.version.id == first and view.can_edit
    assert [(row.code, row.amounts) for row in view.selected.rows] == [
        ('A', {2026: Decimal('.10')}), ('B', {2026: Decimal('0')}), ('#FICTIVE', {}), ('MAX', {2026: MAX_AMOUNT})]
    assert all(type(amount) is Decimal for row in view.selected.rows for amount in row.amounts.values())
    assert authorized.query("SELECT amount FROM eppm.finance_amount WHERE code='MAX'", user_id=3) == [(MAX_AMOUNT,)]
    assert view.catalog == {'A': '=Known description', 'B': 'Second'}
    assert [(row.author, row.created_at, row.number) for row in view.versions] == [('4', 1000, 1)]
    assert "A;'=Known description;0.10" in finance.export(first)
    with localcontext() as context:
        context.prec = 4
        copied = save(finance, values, base_id=first)
        assert finance.view(copied).selected.rows == view.selected.rows
        report = allocated_budget([WbsShare(1, 'MAX', 100), WbsShare(2, 'MAX', 100)], view.selected, 2026)
        assert report.totals == {2026: Decimal('184467440737095516.14')}


def test_native_numbered_history_old_sources_and_immutable_cancellation(finance, authorized):
    first = save(finance)
    approved = save(finance, rows(amount='200'), base_id=first, status='Approved')
    finance.cancel(first)
    canceled = finance.view(first).selected.version
    assert (canceled.status, canceled.previous_status, canceled.canceled_by, canceled.canceled_at) == ('Canceled', 'Draft', '4', 1000)
    proposal = save(finance, rows('B'), base_id=first, status='Proposed')
    direct = save(finance, [], base_id=approved, status='Canceled')
    assert [(row.number, row.status) for row in finance.view().versions] == [(4, 'Canceled'), (3, 'Proposed'), (2, 'Approved'), (1, 'Canceled')]
    assert finance.view(proposal).selected.version.base_id == first
    assert finance.view(first).selected.rows == (BudgetRow('A', {2026: Decimal('100.01')}),)
    assert finance.view(approved).selected.rows[0].amounts == {2026: Decimal('200')}
    for identity in (first, direct):
        with pytest.raises(FinanceError, match='already canceled'):
            finance.cancel(identity)
    for source in ("UPDATE eppm.finance_snapshot SET name='Tampered' WHERE id=%s",
                   'DELETE FROM eppm.finance_snapshot WHERE id=%s',
                   'UPDATE eppm.finance_amount SET amount=0 WHERE snapshot_id=%s',
                   'DELETE FROM eppm.finance_row WHERE snapshot_id=%s',
                   'DELETE FROM eppm.finance_cancellation WHERE snapshot_id=%s'):
        with pytest.raises(psycopg.errors.CheckViolation):
            authorized.query(source, (first,), user_id=4, write=True)


def test_rollover_csv_replacement_and_historical_zero_keep_their_exact_amounts(finance, authorized):
    first = save(finance, rows(amount='0') + rows('B'))
    next_year = service(authorized, year=2027)
    imported = next_year.validate_import(export_csv((BudgetRow('C', {2027: Decimal('123.45')}),), {}, 2027), 2027)
    replacement = [{'code': row.code, 'amounts': {str(y): euro_text(amount) for y, amount in row.amounts.items()}} for row in imported]
    second = save(next_year, replacement, base_id=first, year=2027)
    assert {row.code: row.amounts for row in next_year.view(second).selected.rows} == {
        'A': {2026: Decimal('0')}, 'B': {2026: Decimal('100.01')}, 'C': {2027: Decimal('123.45')}}
    assert '2026' not in next_year.export(second).splitlines()[0]
    with pytest.raises(FinanceError, match='calendar year'):
        save(next_year, year=2026)


def test_all_active_readers_and_finance_only_editors_are_independent_of_projects(finance, authorized):
    first = save(finance)
    reader = service(authorized, 3)
    assert reader.view(first).selected and reader.export(first) and not reader.view().can_edit
    for operation in (lambda: save(reader), lambda: reader.cancel(first), lambda: reader.validate_import('bad', 2026)):
        with pytest.raises(AccessDenied):
            operation()
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
            VALUES (3,'finance_editor','{"kind":"all"}',900,'test setup')""")
    assert reader.view().can_edit
    second = save(reader, base_id=first, status='Approved')
    assert reader.view(second).selected.version.author == '3'
    assert authorized.query('SELECT id FROM eppm.project', user_id=3) == []
    with pytest.raises(AccessDenied):
        gateway(authorized, 3).run(lambda store: store.connection.execute("INSERT INTO eppm.project(name) VALUES ('Denied')"), write=True)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.app_role_assignment WHERE user_id=3')
    with pytest.raises(AccessDenied):
        reader.cancel(second)
    assert reader.export(second)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.app_user SET status='disabled' WHERE id=3")
    for operation in (lambda: reader.view(), lambda: reader.export(first)):
        with pytest.raises(AccessDenied):
            operation()


def test_invalid_saves_and_read_only_store_calls_never_append_partial_history(finance, authorized):
    assert finance.view().selected is None and gateway(authorized).run(lambda store: store.latest()) is None
    first = save(finance, [])
    for operation in (lambda: save(finance, rows(amount='bad')), lambda: save(finance, name=''),
                      lambda: save(finance, status={}), lambda: save(finance, base_id=999),
                      lambda: finance.validate_import('bad', 2026)):
        with pytest.raises(FinanceError):
            operation()
    for identity in (True, -1, 2**63, '1', 999):
        with pytest.raises(FinanceError, match='snapshot'):
            finance.view(identity)
    with pytest.raises(FinanceStorageError, match='writer'):
        gateway(authorized).run(lambda store: store.insert((), number=2, name='No writer', status='Draft', base_id=first))
    assert len(finance.view().versions) == 1


@pytest.mark.parametrize('amount', ['-0.01', '0.001', 'NaN', 'Infinity', '92233720368547758.08'])
def test_native_amount_constraints_preserve_the_existing_range_and_cent_grid(finance, authorized, amount):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.finance_snapshot(id,number,name,status,author,created_at) VALUES (100,100,'Unsealed','Draft','setup',0)")
        connection.execute("INSERT INTO eppm.finance_row VALUES (100,'A',0)")
    with pytest.raises(psycopg.errors.CheckViolation):
        authorized.query("INSERT INTO eppm.finance_amount VALUES (100,'A',2026,%s)", (Decimal(amount),), user_id=4, write=True)
    assert finance.view().versions == ()


@pytest.mark.parametrize('phase', ['amount', 'seal', 'cancel'])
def test_late_native_failures_roll_back_complete_snapshots_and_cancellation_audit(finance, authorized, phase):
    first = save(finance)
    table, action, predicate = {'amount': ('finance_amount', 'INSERT', ''),
                                 'seal': ('finance_snapshot', 'UPDATE', 'WHEN (NEW.sealed)'),
                                 'cancel': ('finance_cancellation', 'INSERT', '')}[phase]
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_finance_test() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Test constraint' USING ERRCODE='23514'; END $$""")
        connection.execute(f'CREATE TRIGGER reject_finance_test AFTER {action} ON eppm.{table} FOR EACH ROW {predicate} EXECUTE FUNCTION eppm.reject_finance_test()')
    with pytest.raises(FinanceStorageError):
        finance.cancel(first) if phase == 'cancel' else save(finance, base_id=first)
    assert len(finance.view().versions) == 1 and finance.view(first).selected.version.status == 'Draft'
    assert authorized.query('SELECT count(*) FROM eppm.finance_snapshot', user_id=3) == [(1,)]
    assert authorized.query('SELECT count(*) FROM eppm.finance_cancellation', user_id=3) == [(0,)]


class GatedGateway(PostgresFinanceGateway):
    def __init__(self, authorized, barrier, attempts, index):
        super().__init__(authorized.database, authorized.key, access=authorized.binding(4).access)
        self.barrier, self.attempts, self.index = barrier, attempts, index

    def run(self, operation, **options):
        def callback(store):
            self.attempts[self.index] += 1
            if self.attempts[self.index] == 1:
                self.barrier.wait(timeout=10)
            return operation(store)
        return super().run(callback, **options)


@pytest.mark.parametrize('existing', [False, True])
def test_concurrent_saves_reselect_the_next_number_without_duplicate_plans(finance, authorized, existing):
    base = save(finance) if existing else None
    barrier, attempts = Barrier(2), [0, 0]
    def create(index):
        actor_service = FinanceService(GatedGateway(authorized, barrier, attempts, index), lambda: date(2026, 6, 1))
        return save(actor_service, rows(amount=f'{index + 1}.01'), base_id=base, name=f'Writer {index}')
    with ThreadPoolExecutor(max_workers=2) as executor:
        identities = list(executor.map(create, range(2)))
    assert len(set(identities)) == 2 and sum(attempts) >= 3
    assert [row.number for row in finance.view().versions] == list(range(3 if existing else 2, 0, -1))
    assert finance.view(identities[0]).selected.rows[0].amounts == {2026: Decimal('1.01')}
    assert finance.view(identities[1]).selected.rows[0].amounts == {2026: Decimal('2.01')}


def test_concurrent_cancellation_replays_to_one_immutable_audit(finance, authorized):
    identity = save(finance, status='Approved')
    barrier, attempts = Barrier(2), [0, 0]
    def cancel(index):
        actor_service = FinanceService(GatedGateway(authorized, barrier, attempts, index), lambda: date(2026, 6, 1))
        try:
            actor_service.cancel(identity)
            return 'saved'
        except FinanceError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(cancel, range(2)))
    assert sorted(results) == ['canceled', 'saved'] and sum(attempts) >= 3
    assert authorized.query('SELECT count(*) FROM eppm.finance_cancellation', user_id=3) == [(1,)]


def test_metadata_rows_and_catalog_keep_one_snapshot_during_concurrent_save_and_cancel(finance, authorized):
    first = save(finance)
    ready, changed = Event(), Event()
    def read():
        def callback(store):
            versions = store.versions()
            ready.set()
            assert changed.wait(timeout=10)
            return versions, store.snapshot(first), store.catalog()
        return gateway(authorized).run(callback)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(read)
        assert ready.wait(timeout=10)
        try:
            save(finance, rows(amount='200'), base_id=first)
            finance.cancel(first)
            with psycopg.connect(authorized.setup.operator_url) as connection:
                connection.execute("UPDATE eppm.wbs SET description='Changed' WHERE code='A'")
        finally:
            changed.set()
        versions, snapshot, catalog = future.result()
    assert len(versions) == 1 and snapshot.version.status == 'Draft'
    assert snapshot.rows[0].amounts == {2026: Decimal('100.01')} and catalog['A'] == '=Known description'


def retry_once(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('CREATE SEQUENCE eppm.finance_attempt')
        connection.execute('GRANT USAGE ON SEQUENCE eppm.finance_attempt TO eppm_runtime')
        connection.execute("""CREATE FUNCTION eppm.retry_finance_once() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF nextval('eppm.finance_attempt')=1 THEN RAISE EXCEPTION 'Known rollback' USING ERRCODE='40001'; END IF;
            RETURN NEW; END $$""")
        connection.execute('CREATE TRIGGER retry_finance_once BEFORE INSERT ON eppm.finance_amount FOR EACH ROW EXECUTE FUNCTION eppm.retry_finance_once()')


def test_retry_preserves_nested_grid_inputs_and_original_base(finance, authorized):
    first = save(finance)
    retry_once(authorized)
    submitted, attempts = rows(amount='0.10'), []
    class ChangedInputGateway(PostgresFinanceGateway):
        def run(self, operation, **options):
            def callback(store):
                attempts.append(1)
                if len(attempts) == 2:
                    submitted[0]['amounts']['2026'] = '999'
                    submitted[0]['code'] = 'Changed'
                return operation(store)
            return super().run(callback, **options)
    actor_service = FinanceService(ChangedInputGateway(authorized.database, authorized.key, access=authorized.binding(4).access), lambda: date(2026, 6, 1))
    second = save(actor_service, submitted, base_id=first)
    assert len(attempts) == 2 and len(finance.view().versions) == 2
    assert finance.view(second).selected.rows == (BudgetRow('A', {2026: Decimal('.10')}),)
    assert finance.view(second).selected.version.base_id == first


def test_revocation_before_retried_binding_prevents_save_and_leaves_no_partial_history(finance, authorized):
    retry_once(authorized)
    attempts = []
    class RevokingDatabase:
        def run(self, operation, *, write, bind):
            def binding(connection):
                attempts.append(1)
                if len(attempts) == 2:
                    with psycopg.connect(authorized.setup.operator_url) as operator:
                        operator.execute("UPDATE eppm.app_session SET revoked=true WHERE session_hash='session-4'")
                bind(connection)
            return authorized.database.run(operation, write=write, bind=binding)
    actor_service = FinanceService(PostgresFinanceGateway(RevokingDatabase(), authorized.key, access=authorized.binding(4).access), lambda: date(2026, 6, 1))
    with pytest.raises(AccessDenied):
        save(actor_service)
    assert len(attempts) == 2
    assert service(authorized, 3).view().versions == ()


def test_native_finance_outage_is_safe_and_does_not_claim_a_known_commit_outcome(finance, authorized, caplog):
    authorized.database.close()
    with pytest.raises(FinanceStorageError) as error:
        save(finance)
    assert 'Check saved versions' in str(error.value)
    assert 'postgresql://' not in str(error.value) + caplog.text
