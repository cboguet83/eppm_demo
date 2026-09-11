"""Dashboard arithmetic, scope, migrations, and real shared-pool aggregation."""

from contextlib import closing
from datetime import date
from decimal import Decimal
import sqlite3

import pytest

from app.domain.access.models import AccessDenied
from app.domain.dashboard import WbsShare, allocated_budget, ancestor, matches, quarterly_shortfall
from app.domain.finance import BudgetSnapshot, BudgetVersion, BudgetRow
from app.domain.resources.models import PoolCapacityDetail, DailyOverassignment
from app.main import create_dashboard_service, create_finance_service
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.schema_init import init_db
from tests.test_business_transaction_security import business as business


def test_allocated_budget_rounds_per_project_row_and_preserves_gaps_and_zero():
    snapshot=BudgetSnapshot(BudgetVersion(1,1,'Plan','Approved','test',0,None),
        (BudgetRow('A',{2026:101,2027:0}),BudgetRow('B',{2026:10000})))
    shares=[WbsShare(1,'A',50),WbsShare(2,'A',50),WbsShare(1,'B',10),WbsShare(1,'MISSING',100)]
    result=allocated_budget(shares+[shares[0]],snapshot,2026)
    assert result.totals=={2026:1102,2027:0}
    assert result.rows[0][1][2026]==51 and 2028 not in result.totals
    assert result.unmatched==('MISSING',)
    assert not allocated_budget(shares,None,2026).totals


def test_hierarchy_senior_self_missing_levels_and_cycles():
    functions={i:{'hierarchy_level':i,'manager_function_id':i-1} for i in range(1,7)}
    assert ancestor(5,3,functions)==3 and ancestor(5,4,functions)==4
    assert ancestor(2,4,functions)==2 and ancestor(3,3,functions)==3
    assert ancestor(None,3,functions) is None
    functions[4]['manager_function_id']=2
    assert ancestor(5,3,functions) is None
    functions[4]['manager_function_id']=5
    assert ancestor(5,3,functions) is None


def test_filter_boolean_semantics():
    project={'id':1,'name':'A','fields':{'manager':['1'],'team':['1','2'],'tags':['A','B']}}
    assert matches(project,{'manager':['1','2'],'tags':['A','B']},True)
    assert not matches(project,{'tags':['A','C']},True)
    assert matches(project,{'tags':['A','C']})
    assert not matches(project,{'manager':['2'],'tags':['A']})


def pool(identity, excess, day='2026-01-01', project=1):
    return PoolCapacityDetail(identity,str(identity),1,1,1,True,excess,
        assignments=[{'project_id':project,'fte_assigned':1,'start_date':day,'end_date':day}],
        daily_overassignments=[DailyOverassignment(day,1,1+excess,excess)])


def test_quarterly_peak_sums_only_concurrent_positive_shortfalls():
    result=quarterly_shortfall([pool(1,-50),pool(2,1),pool(3,2),pool(4,2,'2026-02-01'),pool(5,90,project=2)],{1},2026)
    assert result['2026-Q1']==3
    assert result['2026-Q2']==0 and len(result)==80
    assert quarterly_shortfall([pool(1,2,'2026-03-31'),pool(2,3,'2026-04-01')],{1},2026)['2026-Q2']==3


def test_dashboard_filters_scope_shared_capacity_approved_budget_and_issues(business):
    path,access,admin,editor,manager=business
    with closing(get_db(path)) as conn,conn:
        conn.execute("INSERT INTO wbs(id,code,description) VALUES(1,'A','Budget A')")
        conn.execute('INSERT INTO project_wbs VALUES(1,1,50),(2,1,50)')
        conn.execute("UPDATE resource_pool SET capacity_fte=2 WHERE id=1")
        blocker=conn.execute("SELECT id FROM project_event_type WHERE system_code='blocking_point'").fetchone()[0]
        conn.execute("INSERT INTO project_log_event(project_id,title,event_type_id,status) VALUES(1,'Visible blocker',?,'active'),(2,'Secret blocker',?,'active')",(blocker,blocker))
        conn.execute("UPDATE project_event_type SET name='Renamed' WHERE id=?",(blocker,))
    finance=create_finance_service(path,access=manager);finance.today=lambda:date(2026,1,1)
    first=finance.save([{'code':'A','amounts':{'2026':'100'}}],base_id=None,name='Approved',status='Approved',year=2026)
    newer=finance.save([{'code':'A','amounts':{'2026':'200'}}],base_id=first,name='Newer',status='Approved',year=2026)
    service=create_dashboard_service(path,access=editor);service.today=lambda:date(2026,1,1)
    catalog=service.catalog()
    assert [row['id'] for row in catalog.projects]==[1]
    assert service.report([1]).budget.totals=={2026:10000}
    assert service.report([1]).issue_count==1
    assert service.issues([1],'en')[0]['title']=='Visible blocker'
    assert service.shortages([1])['2026-Q1']==1  # Hidden project's 2 FTE still competes.
    revision=service.revision()
    finance.cancel(newer)
    assert service.revision()!=revision and service.report([1]).budget.totals=={2026:5000}
    for operation in [lambda:service.report([2]),lambda:service.shortages([2]),lambda:service.issues([2],'en')]:
        with pytest.raises(AccessDenied):operation()
    for assignment in access.assignments(admin,editor.actor.user_id):access.revoke(admin,assignment['id'])
    assert service.catalog().projects==[]
    access.set_status(admin,editor.actor.user_id,'disabled')
    with pytest.raises(AccessDenied):service.revision()


def test_organization_labels_membership_facets_and_dynamic_fields(business):
    path,_,_,_,manager=business
    with closing(get_db(path)) as conn,conn:
        for identity in range(3,7):
            conn.execute('INSERT INTO function(function_id,name,hierarchy_level,manager_function_id) VALUES(?,?,?,?)',
                         (identity,f'Role {identity}',identity,identity-1 if identity>3 else None))
            conn.execute('INSERT INTO employee(firstname,lastname,email,employee_code,function_id) VALUES(?,?,?,?,?)',
                         ('Same','Name',f'{identity}@example.test',str(identity),identity))
        conn.execute("INSERT INTO team(team_id,team_name) VALUES(1,'First'),(2,'Second')")
        conn.execute('INSERT INTO team_function(team_id,function_id) VALUES(1,5),(2,5)')
        conn.execute('UPDATE project SET function_id=5 WHERE id=1')
        conn.execute('UPDATE project SET function_id=6 WHERE id=2')
        conn.execute("INSERT INTO schema_parameters(param_id,param_name,param_type,applies_to_all) VALUES('PRM_001','code courrier','TEXT',1)")
        conn.execute("INSERT INTO project_property_value(project_id,param_id,kind,text_value) VALUES(1,'PRM_001','text','MAIL-1')")
    service=create_dashboard_service(path,access=manager)
    catalog=service.catalog();first=catalog.projects[1] if catalog.projects[1]['id']==1 else catalog.projects[0]
    assert first['fields']['level3']==['3'] and first['fields']['level4']==['4']
    assert first['fields']['team']==['1','2'] and first['fields']['PRM_001']==['MAIL-1']
    assert catalog.labels['manager']['5']!=catalog.labels['manager']['6']
    assert service.choices(catalog,{'team':['1'],'manager':['6']},'manager')==['5','6']
    init_db(path)
    assert service.catalog().projects


def test_dashboard_migration_preserves_events_and_revokes_only_pre_upgrade_sessions():
    from app.infrastructure.database.dashboard_migration import migrate_dashboard

    with closing(sqlite3.connect(':memory:')) as conn:
        conn.executescript('''
            CREATE TABLE schema_migration(version TEXT PRIMARY KEY);
            CREATE TABLE project_event_type(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE project_log_event(id INTEGER PRIMARY KEY, event_type_id INTEGER, title TEXT);
            CREATE TABLE app_session(session_hash TEXT PRIMARY KEY, revoked INTEGER);
            INSERT INTO project_event_type VALUES(1,'Blocking Point'),(2,'Decision');
            INSERT INTO project_log_event VALUES(7,1,'Preserved issue');
            INSERT INTO app_session VALUES('old',0),('already-revoked',1);
        ''')
        with conn:
            migrate_dashboard(conn)
        assert conn.execute('SELECT * FROM project_log_event').fetchall() == [(7, 1, 'Preserved issue')]
        assert conn.execute('SELECT revoked FROM app_session').fetchall() == [(1,), (1,)]
        with conn:
            conn.execute("UPDATE project_event_type SET name='Renamed blocker' WHERE id=1")
            conn.execute("INSERT INTO app_session VALUES('new',0)")
            migrate_dashboard(conn)
        assert conn.execute("SELECT system_code FROM project_event_type WHERE id=1").fetchone()[0] == 'blocking_point'
        assert conn.execute("SELECT revoked FROM app_session WHERE session_hash='new'").fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM schema_migration').fetchone()[0] == 1


def test_dashboard_storage_failure_is_safe_and_empty_scope_has_no_finance_source(business, monkeypatch):
    from app.application.exceptions import ProjectStorageError
    from app.infrastructure.repositories import dashboard

    path, _, _, editor, _ = business
    service = create_dashboard_service(path, access=editor)
    assert service.report([]).approved is None
    assert all(value == 0 for value in service.shortages([]).values())
    def unavailable(_):
        raise sqlite3.OperationalError('internal storage details')
    monkeypatch.setattr(dashboard, 'get_db', unavailable)
    with pytest.raises(ProjectStorageError, match='Please try again') as failure:
        service.catalog()
    assert 'internal storage details' not in str(failure.value)


def test_undated_assignments_use_today_and_invalidate_on_calendar_day_change(business):
    path, _, _, _, manager = business
    with closing(get_db(path)) as conn, conn:
        conn.execute("INSERT INTO project(id,name) VALUES(3,'Undated project')")
        conn.execute("INSERT INTO resource_pool(id,name,capacity_fte) VALUES(2,'Undated pool',1)")
        conn.execute('INSERT INTO resource_pool_assignment(project_id,pool_id,fte_assigned) VALUES(3,2,2)')
    service = create_dashboard_service(path, access=manager)
    service.today = lambda: date(2026, 9, 30)
    revision = service.revision()
    assert service.shortages([3])['2026-Q3'] == 1
    assert service.shortages([3])['2026-Q1'] == 0
    service.today = lambda: date(2026, 10, 1)
    assert service.revision() != revision
    assert service.shortages([3])['2026-Q4'] == 1


def test_pool_facets_exclude_finished_projects_and_preserve_numeric_project_order(business):
    path, _, _, _, manager = business
    with closing(get_db(path)) as conn, conn:
        conn.executemany('INSERT INTO project(id,name,status) VALUES(?,?,?)',
                         [(3,'AAA','Completed'),(4,'BBB','Cancelled'),(5,'CCC','Canceled'),(6,'AAA','In Progress')])
    service = create_dashboard_service(path, access=manager)
    catalog = service.catalog()
    assert [row['id'] for row in catalog.projects] == [1, 2, 6]
    assert service.choices(catalog, {}, 'pool') == ['', '1']
    assert [row['id'] for row in service.filtered(catalog, {'pool':['1']})] == [1,2]
    assert service.filtered(catalog, {'pool':['']})[0]['id'] == 6
    assert matches(catalog.projects[0], {'pool':['1','other']}, True)


def test_quarter_capacity_uses_concurrent_daily_totals_and_calendar_overrides():
    from dataclasses import replace
    from app.domain.dashboard import quarterly_capacity, responsible_pools, quarter_bounds
    first = replace(pool(1, 2), effective_capacity_fte=2, has_assigned_resources=True,
                    daily_assigned_capacity={'2026-01-01':4})
    second = replace(pool(2, 1, '2026-02-01'), effective_capacity_fte=3, has_assigned_resources=True,
                     daily_assigned_capacity={'2026-02-01':5})
    capacity = quarterly_capacity([first, second, first], 2026)
    assert capacity['2026-Q1'] == 7  # Different-day capacity peaks are not added.
    assert capacity['2026-Q2'] == 5
    start, end = quarter_bounds('2026-Q1', 2026)
    assert responsible_pools([first, second], {1}, start, end) == {1,2}
    with pytest.raises(ValueError):
        quarter_bounds('2026-Q5', 2026)


def test_chart_drillthrough_includes_all_authorized_consumers_but_never_hidden_projects(business):
    path, _, _, editor, manager = business
    with closing(get_db(path)) as conn, conn:
        conn.execute('UPDATE resource_pool SET capacity_fte=1 WHERE id=1')
    restricted = create_dashboard_service(path, access=editor)
    unrestricted = create_dashboard_service(path, access=manager)
    restricted.today = unrestricted.today = lambda: date(2026, 6, 1)
    assert restricted.consuming_projects([1], '2026-Q1') == [1]
    assert unrestricted.consuming_projects([1], '2026-Q1') == [1,2]
    assert restricted.consuming_projects([1], '2027-Q1') == []
    with pytest.raises(AccessDenied):
        restricted.consuming_projects([2], '2026-Q1')
