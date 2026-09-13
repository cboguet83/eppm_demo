"""Exact finance validation, immutable snapshots and real transaction boundaries."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from decimal import Decimal
import csv
import io
import sqlite3
from unittest.mock import patch

import pytest

from app.application.services.finance import FinanceService
from app.domain.access.models import AccessDenied, Permission, ProjectScope, validate_assignment
from app.domain.finance import BudgetRow, FinanceError, euro_text, export_csv, normalize_rows, parse_amount, parse_csv, preserve_history
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.finance_migration import migrate_finance
from app.infrastructure.database.schema_init import init_db
from app.infrastructure.repositories.finance import SqliteFinanceGateway
from tests.test_business_transaction_security import business as business


def finance(path, access, year=2026):
    return FinanceService(SqliteFinanceGateway(path, access), lambda: date(year, 6, 1))


def rows(code='A', amount='100.01', year=2026):
    return [{'code': code, 'amounts': {str(year): amount}}]


@pytest.mark.parametrize('value,expected', [('', None), (' ', None), ('0', Decimal('0')), ('0.10', Decimal('0.10')),
    ('100,01', Decimal('100.01')), ('92233720368547758.07', Decimal('92233720368547758.07'))])
def test_finance_uses_exact_decimal_euros_and_distinguishes_blank_from_zero(value, expected):
    assert parse_amount(value, 2, 2026) == expected


@pytest.mark.parametrize('value', ['-1', 'NaN', 'inf', '1e3', '1.001', '1,000.00', '=1+1', '92233720368547758.08', True, 1.1, None])
def test_invalid_amount_explains_row_and_year(value):
    with pytest.raises(FinanceError, match='Row 2, year 2026'):
        parse_amount(value, 2, 2026)


@pytest.mark.parametrize('raw,key', [([{'code':'A B','amounts':{}}], 'code'), (rows()*2, 'duplicate'),
    (rows(year=2025), 'years'), (rows(year=2041), 'years'), ([{}], 'rows'), (None,'rows'),
    ([{'code':None,'amounts':{}}], 'code')])
def test_grid_rejects_invalid_codes_duplicate_rows_and_historical_edits(raw, key):
    with pytest.raises(FinanceError) as caught:
        normalize_rows(raw, 2026)
    assert caught.value.code == key


def test_numbered_versions_allow_old_sources_and_audited_cancellation(business):
    path, _, _, _, manager = business
    service = finance(path, manager)
    first = service.save(rows(), base_id=None, name='Baseline', status='Draft', year=2026)
    approved = service.save(rows(amount='200'), base_id=first, name='Baseline', status='Approved', year=2026)
    service.cancel(first)
    canceled = service.view(first).selected.version
    assert (canceled.number,canceled.status,canceled.previous_status)==(1,'Canceled','Draft')
    assert canceled.canceled_by==manager.audit_actor and canceled.canceled_at==1000
    copy = service.save(rows('B'), base_id=first, name='Alternative', status='Proposed', year=2026)
    direct = service.save(rows('C'), base_id=approved, name='Stopped', status='Canceled', year=2026)
    assert [(v.number,v.status) for v in service.view().versions]==[(4,'Canceled'),(3,'Proposed'),(2,'Approved'),(1,'Canceled')]
    assert service.view(copy).selected.version.base_id==first
    assert service.view(first).selected.rows[0].amounts=={2026:Decimal('100.01')}
    assert service.view(approved).selected.rows[0].amounts=={2026:Decimal('200.00')}
    assert service.export(first)
    for identity in [first,direct]:
        with pytest.raises(FinanceError,match='already canceled'): service.cancel(identity)
    assert len(service.view().versions)==4


def test_calendar_rollover_and_csv_replacement_preserve_past_codes_and_zero(business):
    path, _, _, _, manager = business
    service = finance(path, manager)
    first = service.save(rows(amount='0') + rows('B'), base_id=None, status='Draft', name='Year 1', year=2026)
    next_year = finance(path, manager, 2027)
    imported = next_year.validate_import(export_csv((BudgetRow('C',{2027:Decimal('123.45')}),), {}, 2027), 2027)
    second = next_year.save([{'code':r.code,'amounts':{str(y):euro_text(v) for y,v in r.amounts.items()}} for r in imported],
                            base_id=first, status='Draft',name='Baseline', year=2027)
    saved = {row.code:row.amounts for row in next_year.view(second).selected.rows}
    assert saved == {'A':{2026:Decimal('0')},'B':{2026:Decimal('100.01')},'C':{2027:Decimal('123.45')}}
    assert '2026' not in next_year.export(second).splitlines()[0]
    assert len(parse_csv(next_year.export(second),2027)) == 3
    with pytest.raises(FinanceError, match='calendar year'):
        next_year.save(rows(), base_id=second, status='Draft',name='Baseline', year=2026)


def test_csv_round_trip_and_precise_import_errors():
    source = (BudgetRow('-ABC',{2025:Decimal('0.12'),2026:Decimal('0.10'),2040:Decimal('9.99')}), BudgetRow('#FICTIVE',{}))
    text = export_csv(source, {'-ABC':'=DO_NOT_EXECUTE()'}, 2026)
    assert "'-ABC;'=DO_NOT_EXECUTE()" in text
    assert parse_csv('\ufeff'+text,2026) == (BudgetRow('-ABC',{2026:Decimal('0.10'),2040:Decimal('9.99')}),BudgetRow('#FICTIVE',{}))
    csv_rows = list(csv.reader(io.StringIO(text),delimiter=';'))
    csv_rows[1][2] = '12,34'
    out = io.StringIO(); csv.writer(out).writerows(csv_rows)
    assert parse_csv(out.getvalue(),2026)[0].amounts[2026] == Decimal('12.34')
    for content, key in [('wrong\n','headers'), (text+'too;short\n','columns'), (text.replace('0.10','-1'),'amount'),
                         (text+text.splitlines()[1]+'\n','duplicate'), ('\x00','csv'), ('x'*2097153,'csv')]:
        with pytest.raises(FinanceError) as caught:
            parse_csv(content,2026)
        assert caught.value.code == key


def test_finance_editor_and_all_active_readers_are_independent_of_project_scope(business):
    path, access, admin, editor, manager = business
    for assignment in access.assignments(admin,editor.actor.user_id):
        access.revoke(admin,assignment['id'])
    reader = finance(path,editor)
    first = finance(path,manager).save(rows(),base_id=None,status='Draft',name='Shared',year=2026)
    assert reader.view(first).selected and reader.export(first) and not reader.view().can_edit
    with pytest.raises(AccessDenied):
        reader.save(rows(),base_id=first,status='Draft',name='Baseline',year=2026)
    with pytest.raises(AccessDenied):
        reader.validate_import('',2026)
    grant = access.grant(admin,editor.actor.user_id,'finance_editor',{'kind':'all'})
    assert reader.view().can_edit
    approved = reader.save(rows(),base_id=first,name='Shared',status='Approved',year=2026)
    with access.gateway.transaction() as store:
        assert not editor.policy.projects(store,editor.actor,Permission.READ)
    access.revoke(admin,grant)
    with pytest.raises(AccessDenied):
        reader.cancel(approved)
    access.set_status(admin,editor.actor.user_id,'disabled')
    with pytest.raises(AccessDenied):
        reader.export(first)
    with pytest.raises(AccessDenied):
        reader.view()
    with pytest.raises(ValueError):
        validate_assignment('finance_editor',ProjectScope('projects',(1,)))


def test_concurrent_versions_and_invalid_saves_do_not_partially_write(business):
    path, _, _, _, manager = business
    service=finance(path,manager)
    first=service.save(rows(),base_id=None,status='Draft',name='Base',year=2026)
    def save_once(_):
        try:
            return service.save(rows(),base_id=first,status='Draft',name='Baseline',year=2026)
        except FinanceError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(save_once,range(2)))
    assert all(type(result) is int for result in results)
    assert [v.number for v in service.view().versions]==[3,2,1]
    latest=service.view().selected.version.id
    for operation in [lambda:service.save(rows(amount='bad'),base_id=latest,status='Draft',name='Baseline',year=2026),
                      lambda:service.save(rows(),base_id=latest,status='Draft',name='',year=2026),
                      lambda:service.save(rows(),base_id=latest,name='Invalid',status='Invalid',year=2026)]:
        with pytest.raises(FinanceError): operation()
    assert len(service.view().versions)==3


def test_migrations_preserve_roles_security_triggers_and_snapshot_integrity(business):
    path, _, _, _, manager = business
    service=finance(path,manager)
    first=service.save(rows(),base_id=None,status='Draft',name='Base',year=2026)
    with closing(get_db(path)) as connection:
        assignments=connection.execute('SELECT * FROM app_role_assignment').fetchall()
        triggers=connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name").fetchall()
    init_db(path)
    with closing(get_db(path)) as connection, connection:
        migrate_finance(connection)
        assert connection.execute('SELECT * FROM app_role_assignment').fetchall()==assignments
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name").fetchall()==triggers
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        for sql in [f"UPDATE finance_snapshot SET name='changed' WHERE id={first}",
                    'DELETE FROM finance_row', 'UPDATE finance_amount SET cents=1',
                    f"INSERT INTO finance_row VALUES({first},'B',2)",
                    f"INSERT OR REPLACE INTO finance_snapshot(id,number,name,status,author,created_at) VALUES({first},1,'Replace','Draft','test',0)"]:
            with pytest.raises(sqlite3.IntegrityError): connection.execute(sql)
    assert service.view(first).selected.rows[0].amounts=={2026:Decimal('100.01')}


def test_existing_access_database_upgrades_without_losing_grants_or_scope_invalidation(tmp_path):
    path=str(tmp_path/'pre-finance.db')
    with patch('app.infrastructure.database.schema_init.migrate_finance'), patch('app.infrastructure.database.schema_init.migrate_finance_versions'):
        init_db(path)
    with closing(get_db(path)) as connection, connection:
        connection.execute("INSERT INTO app_user(id,status,created_at,updated_at) VALUES(1,'active',0,0)")
        connection.execute("INSERT INTO project(id,name) VALUES(1,'Old project')")
        connection.execute("""INSERT INTO app_role_assignment VALUES(10,1,'project_editor',
            '{"kind":"projects","project_ids":[1]}','',0,'original')""")
        connection.execute("UPDATE sqlite_sequence SET seq=400 WHERE name='app_role_assignment'")
        connection.execute("""INSERT INTO app_security_audit(occurred_at,actor,target,action,outcome,correlation_id,details_json)
            VALUES(0,'original','1','test','success','reference','{}')""")
    init_db(path)
    with closing(get_db(path)) as connection, connection:
        assert connection.execute('SELECT id,role,created_by FROM app_role_assignment').fetchall()==[(10,'project_editor','original')]
        cursor=connection.execute("""INSERT INTO app_role_assignment(user_id,role,scope_json,created_at,created_by)
            VALUES(1,'finance_editor','{"kind":"all"}',0,'new')""")
        assert cursor.lastrowid==401
        connection.execute('DELETE FROM project WHERE id=1')
        assert connection.execute('SELECT invalid_reason FROM app_role_assignment WHERE id=10').fetchone()[0]
        assert connection.execute('SELECT count(*) FROM app_security_audit').fetchone()[0]==1
        with pytest.raises(sqlite3.IntegrityError): connection.execute('DELETE FROM app_security_audit')
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()


def test_finance_download_reauthorizes_active_users_on_every_fetch(business):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient
    from app.infrastructure.authentication.finance import FinanceDownloadRoutes
    from app.application.services.business_access import BusinessAccess
    from app.domain.access.models import VerifiedIdentity

    path, access, admin, _, manager=business
    first=finance(path,manager).save(rows(),base_id=None,status='Draft',name='Shared',year=2026)
    cookie=access.sign_in(VerifiedIdentity(access.issuer,'download-reader','','Reader',1000,100000,True))
    reader=access.actor(cookie)
    access.set_status(admin,reader.user_id,'active')
    routes=FinanceDownloadRoutes(access,lambda actor,identity:finance(path,BusinessAccess(actor,access.policy)).export(identity))
    with TestClient(Starlette(routes=routes.routes())) as client:
        url=f'/downloads/finance/{first}/budget.csv'
        assert client.get(url).status_code==403
        client.cookies.set('eppm_session',cookie)
        response=client.get(url)
        assert response.status_code==200 and response.text.startswith('\ufeffwbs_code;description;2026')
        assert response.headers['cache-control']=='no-store'
        assert 'attachment' in response.headers['content-disposition']
        assert client.head(url).status_code==200
        assert client.get('/downloads/finance/999/budget.csv').status_code==403
        access.set_status(admin,reader.user_id,'disabled')
        assert client.get(url).status_code==403


def test_finance_values_survive_project_and_catalog_reseeding(business):
    from app.operator_services import create_maintenance_service
    path, _, _, _, manager=business
    service=finance(path,manager)
    first=service.save(rows(),base_id=None,status='Draft',name='Keep',year=2026)
    create_maintenance_service(path).flush(flush_all=True)
    assert service.view(first).selected.rows[0].amounts=={2026:Decimal('100.01')}


def test_finance_saves_do_not_invalidate_portfolio_or_permission_caches(business):
    from app.infrastructure.database.display_revision import read_display_revision
    path,_,_,_,manager=business
    with closing(get_db(path)) as connection:
        before=read_display_revision(connection)
    service=finance(path,manager)
    first=service.save(rows(),base_id=None,status='Draft',name='Independent',year=2026)
    service.cancel(first)
    with closing(get_db(path)) as connection:
        assert read_display_revision(connection)==before


def test_limits_account_for_history_multibyte_files_and_malformed_csv():
    with pytest.raises(FinanceError,match='10,000'):
        preserve_history(tuple(BudgetRow(str(i),{2025:Decimal('0.01')}) for i in range(10000)),(BudgetRow('new',{}),),2026)
    header=export_csv((),{},2026)
    for text in ['é'*1100000,'\ud800',header+'"unclosed',header+('A;'+';'*15+'\n')*10001]:
        with pytest.raises(FinanceError): parse_csv(text,2026)


def test_invalid_statuses_and_storage_boundaries(business,tmp_path):
    from app.application.exceptions import FinanceStorageError
    path,_,_,_,manager=business
    service=finance(path,manager)
    for status in ['',None,{},'invalid']:
        with pytest.raises(FinanceError,match='Choose'):
            service.save([],base_id=None,status=status,name='Base',year=2026)
    first=service.save([],base_id=None,status='Draft',name='Base',year=2026)
    for identity in [True,-1,2**63,'1']:
        with pytest.raises(FinanceError,match='snapshot'):
            service.view(identity)
    with service.gateway.transaction() as store:
        with pytest.raises(FinanceStorageError,match='writer'):
            store.insert((),number=2,name='No writer',status='Draft',base_id=first)
    with pytest.raises(FinanceStorageError,match='unavailable'):
        finance(str(tmp_path/'unmigrated.db'),manager).view()


def test_finance_download_returns_safe_storage_errors(business):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient
    from app.infrastructure.authentication.finance import FinanceDownloadRoutes
    from app.application.exceptions import FinanceStorageError
    from app.domain.access.models import VerifiedIdentity
    path,access,admin,_,_=business
    cookie=access.sign_in(VerifiedIdentity(access.issuer,'download-error','','Reader',1000,100000,True))
    actor=access.actor(cookie);access.set_status(admin,actor.user_id,'active')
    def unavailable(actor,snapshot_id):
        raise FinanceStorageError('Internal database details')
    with TestClient(Starlette(routes=FinanceDownloadRoutes(access,unavailable).routes())) as client:
        client.cookies.set('eppm_session',cookie)
        response=client.get('/downloads/finance/1/budget.csv')
        assert response.status_code==503 and response.json()['error']['code']=='download_failed'
        assert 'Internal' not in response.text


def test_blank_grid_rows_are_ignored_and_amount_without_code_identifies_row():
    assert normalize_rows([{'code':' ','amounts':{'2026':''}},*rows(),{'code':'','amounts':{}}],2026)==(BudgetRow('A',{2026:Decimal('100.01')}),)
    with pytest.raises(FinanceError,match='Row 2'):
        normalize_rows([{'code':'','amounts':{}},{'code':'','amounts':{'2026':'0'}}],2026)


def test_v2_migration_preserves_legacy_versions_references_and_constraints(tmp_path):
    from app.infrastructure.database.finance_versions_migration import migrate_finance_versions
    path=str(tmp_path/'legacy-finance.db')
    with patch('app.infrastructure.database.schema_init.migrate_finance_versions'):
        init_db(path)
    with closing(get_db(path)) as connection, connection:
        for identity,major,minor,base in [(10,1,0,None),(11,2,0,10),(12,1,1,10)]:
            connection.execute("INSERT INTO finance_snapshot(id,major,minor,name,status,author,created_at,base_id) VALUES(?,?,?,'Legacy','Approved','original',?,?)",(identity,major,minor,identity,base))
            connection.execute("INSERT INTO finance_row VALUES(?,'A',0)",(identity,))
            connection.execute("INSERT INTO finance_amount VALUES(?,'A',2025,123)",(identity,))
            connection.execute('UPDATE finance_snapshot SET sealed=1 WHERE id=?',(identity,))
        connection.execute("UPDATE sqlite_sequence SET seq=100 WHERE name='finance_snapshot'")
        before=connection.execute('SELECT * FROM finance_amount').fetchall()
    init_db(path)
    with closing(get_db(path)) as connection, connection:
        migrate_finance_versions(connection)
        assert connection.execute('SELECT id,number,name,status,author,created_at,base_id FROM finance_snapshot ORDER BY number').fetchall()==[
            (10,1,'Legacy','Approved','original',10,None),(11,2,'Legacy','Approved','original',11,10),(12,3,'Legacy','Approved','original',12,10)]
        assert connection.execute('SELECT * FROM finance_amount').fetchall()==before
        assert connection.execute("SELECT seq FROM sqlite_sequence WHERE name='finance_snapshot'").fetchone()[0]==100
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        connection.execute("INSERT INTO finance_cancellation VALUES(10,'Approved','editor',200)")
        for sql in ["UPDATE finance_snapshot SET status='Draft' WHERE id=10", 'DELETE FROM finance_snapshot',
                    "UPDATE finance_cancellation SET author='forged'", 'DELETE FROM finance_cancellation',
                    "INSERT OR REPLACE INTO finance_cancellation VALUES(10,'Approved','forged',300)",
                    "INSERT INTO finance_cancellation VALUES(11,'Draft','forged',300)"]:
            with pytest.raises(sqlite3.IntegrityError): connection.execute(sql)


def test_failed_version_migration_rolls_back_and_can_be_retried(tmp_path):
    from app.infrastructure.database.finance_versions_migration import migrate_finance_versions

    class InterruptedMigration(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if "CREATE TABLE finance_cancellation" in sql:
                raise sqlite3.OperationalError("Injected migration failure")
            return super().execute(sql, parameters)

    path=str(tmp_path/'rollback.db')
    with patch('app.infrastructure.database.schema_init.migrate_finance_versions'):
        init_db(path)
    with closing(sqlite3.connect(path, factory=InterruptedMigration)) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        with pytest.raises(sqlite3.OperationalError,match='Injected'), connection:
            connection.execute('BEGIN IMMEDIATE')
            migrate_finance_versions(connection)
        assert 'major' in {row[1] for row in connection.execute('PRAGMA table_info(finance_snapshot)')}
        assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name='finance_snapshot_v2'").fetchone()
        assert not connection.execute("SELECT 1 FROM schema_migration WHERE version='finance-budget-v2'").fetchone()
    init_db(path)
    with closing(get_db(path)) as connection:
        assert 'number' in {row[1] for row in connection.execute('PRAGMA table_info(finance_snapshot)')}
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()


def test_concurrent_cancellation_records_one_audit_and_keeps_budget(business):
    path,_,_,_,manager=business
    service=finance(path,manager)
    identity=service.save(rows(),base_id=None,name='Cancel once',status='Approved',year=2026)
    def cancel_once(_):
        try:
            service.cancel(identity)
            return 'success'
        except FinanceError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(cancel_once,range(2)))==['canceled','success']
    assert len(service.view().versions)==1
    assert service.view(identity).selected.rows==(BudgetRow('A',{2026:Decimal('100.01')}),)
