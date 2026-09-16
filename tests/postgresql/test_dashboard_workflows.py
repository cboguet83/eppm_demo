"""Native dashboard catalog, issue, scope and calendar workflows."""

from tests.postgresql.plan_fixtures import seed_test_plans
from datetime import date
from decimal import Decimal
import psycopg
import pytest

from app.domain.access.models import AccessDenied
from app.domain.dashboard import matches
from app.main import create_dashboard_service, create_finance_service
from app.infrastructure.postgresql.migration import migrate
from tests.postgresql.test_dashboard_ui import business, runtime


def test_repeated_migrations_preserve_events_and_current_session_states(business, authorized):
    """Native migration reentry never repeats the retired SQLite session upgrade."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        blocker = connection.execute(
            "SELECT id FROM eppm.project_event_type WHERE system_code='blocking_point'"
        ).fetchone()[0]
        event = connection.execute(
            "INSERT INTO eppm.project_log_event(project_id,title,event_type_id) "
            "VALUES(1,'Preserved issue',%s) RETURNING id", (blocker,)
        ).fetchone()[0]
        connection.execute("UPDATE eppm.project_event_type SET name='Renamed blocker' WHERE id=%s", (blocker,))
        connection.execute("UPDATE eppm.app_session SET revoked=true WHERE session_hash='session-2'")
        before = connection.execute(
            "SELECT session_hash,revoked FROM eppm.app_session ORDER BY session_hash"
        ).fetchall()
    migrate(authorized.setup.operator_url)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute(
            "SELECT id,title,event_type_id FROM eppm.project_log_event"
        ).fetchall() == [(event, 'Preserved issue', blocker)]
        assert connection.execute(
            "SELECT name,system_code FROM eppm.project_event_type WHERE id=%s", (blocker,)
        ).fetchone() == ('Renamed blocker', 'blocking_point')
        assert connection.execute(
            "SELECT session_hash,revoked FROM eppm.app_session ORDER BY session_hash"
        ).fetchall() == before


def test_dashboard_filters_scope_shared_capacity_approved_budget_and_issues(business, authorized):
    path,access,admin,editor,manager=business
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("INSERT INTO eppm.wbs(id,code,description) VALUES(1,'A','Budget A')")
        conn.execute('INSERT INTO eppm.project_wbs VALUES(1,1,50),(2,1,50)')
        conn.execute("UPDATE eppm.resource_pool SET capacity_fte=2 WHERE id=1")
        blocker=conn.execute("SELECT id FROM eppm.project_event_type WHERE system_code='blocking_point'").fetchone()[0]
        conn.execute("INSERT INTO eppm.project_log_event(project_id,title,event_type_id,status) VALUES(1,'Visible blocker',%s,'active'),(2,'Secret blocker',%s,'active')",(blocker,blocker))
        conn.execute("UPDATE eppm.project_event_type SET name='Renamed' WHERE id=%s",(blocker,))
    finance=create_finance_service(path,access=manager);finance.today=lambda:date(2026,1,1)
    first=finance.save([{'code':'A','amounts':{'2026':'100'}}],base_id=None,name='Approved',status='Approved',year=2026)
    newer=finance.save([{'code':'A','amounts':{'2026':'200'}}],base_id=first,name='Newer',status='Approved',year=2026)
    service=create_dashboard_service(path,access=editor);service.today=lambda:date(2026,1,1)
    catalog=service.catalog()
    assert [row['id'] for row in catalog.projects]==[1]
    assert service.report([1]).budget.totals=={2026:Decimal('100.00')}
    assert service.report([1]).issue_count==1
    assert service.issues([1],'en')[0]['title']=='Visible blocker'
    assert service.shortages([1])['2026-Q1']==1  # Hidden project's 2 FTE still competes.
    revision=service.revision()
    finance.cancel(newer)
    assert service.revision()!=revision and service.report([1]).budget.totals=={2026:Decimal('50.00')}
    for operation in [lambda:service.report([2]),lambda:service.shortages([2]),lambda:service.issues([2],'en')]:
        with pytest.raises(AccessDenied):operation()
    for assignment in access.assignments(admin,editor.actor.user_id):access.revoke(admin,assignment['id'])
    assert service.catalog().projects==[]
    access.set_status(admin,editor.actor.user_id,'disabled')
    with pytest.raises(AccessDenied):service.revision()



def test_organization_labels_membership_facets_and_dynamic_fields(business, authorized):
    path,_,_,_,manager=business
    with psycopg.connect(authorized.setup.operator_url) as conn:
        for identity in range(3,7):
            conn.execute('INSERT INTO eppm.function(function_id,name,hierarchy_level,manager_function_id) VALUES(%s,%s,%s,%s)',
                         (identity,f'Role {identity}',identity,identity-1 if identity>3 else None))
            conn.execute('INSERT INTO eppm.employee(firstname,lastname,email,employee_code,function_id) VALUES(%s,%s,%s,%s,%s)',
                         ('Same','Name',f'{identity}@example.test',str(identity),identity))
        conn.execute("INSERT INTO eppm.team(team_id,team_name) VALUES(1,'First'),(2,'Second')")
        conn.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES(1,5),(2,5)')
        conn.execute('UPDATE eppm.project SET function_id=5 WHERE id=1')
        conn.execute('UPDATE eppm.project SET function_id=6 WHERE id=2')
        conn.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type,applies_to_all) VALUES('PRM_001','code courrier','TEXT',true)")
        conn.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) VALUES(1,'PRM_001','text','MAIL-1')")
    service=create_dashboard_service(path,access=manager)
    catalog=service.catalog();first=catalog.projects[1] if catalog.projects[1]['id']==1 else catalog.projects[0]
    assert first['fields']['level3']==['3'] and first['fields']['level4']==['4']
    assert first['fields']['team']==['1','2'] and first['fields']['PRM_001']==['MAIL-1']
    assert catalog.labels['manager']['5']!=catalog.labels['manager']['6']
    assert service.choices(catalog,{'team':['1'],'manager':['6']},'manager')==['5','6']
    migrate(authorized.setup.operator_url)
    assert service.catalog().projects



def test_dashboard_storage_failure_is_safe_and_empty_scope_has_no_finance_source(business):
    from app.application.exceptions import ProjectStorageError

    runtime, _, _, editor, _ = business
    service = create_dashboard_service(runtime, access=editor)
    assert service.report([]).approved is None
    assert all(value == 0 for value in service.shortages([]).values())
    runtime.database.close()
    with pytest.raises(ProjectStorageError, match='Please try again') as failure:
        service.catalog()
    assert 'postgresql' not in str(failure.value).lower()


def test_undated_assignments_use_today_and_invalidate_on_calendar_day_change(business, authorized):
    path, _, _, _, manager = business
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("INSERT INTO eppm.project(id,name) VALUES(3,'Undated project')")
        seed_test_plans(conn)
        conn.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(2,'Undated pool',1)")
        conn.execute('INSERT INTO eppm.resource_pool_assignment(project_id,pool_id,fte_assigned,project_plan_id) VALUES (3,2,2,(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))')
    service = create_dashboard_service(path, access=manager)
    service.today = lambda: date(2026, 9, 30)
    revision = service.revision()
    assert service.shortages([3])['2026-Q3'] == 1
    assert service.shortages([3])['2026-Q1'] == 0
    service.today = lambda: date(2026, 10, 1)
    assert service.revision() != revision
    assert service.shortages([3])['2026-Q4'] == 1



def test_pool_facets_exclude_finished_projects_and_preserve_numeric_project_order(business, authorized):
    path, _, _, _, manager = business
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.cursor().executemany('INSERT INTO eppm.project(id,name,status) VALUES(%s,%s,%s)',
                         [(3,'AAA','Completed'),(4,'BBB','Cancelled'),(5,'CCC','Canceled'),(6,'AAA','In Progress')])
    service = create_dashboard_service(path, access=manager)
    catalog = service.catalog()
    assert [row['id'] for row in catalog.projects] == [1, 2, 6]
    assert service.choices(catalog, {}, 'pool') == ['', '1']
    assert [row['id'] for row in service.filtered(catalog, {'pool':['1']})] == [1,2]
    assert service.filtered(catalog, {'pool':['']})[0]['id'] == 6
    assert matches(catalog.projects[0], {'pool':['1','other']}, True)



def test_chart_drillthrough_includes_all_authorized_consumers_but_never_hidden_projects(business, authorized):
    path, _, _, editor, manager = business
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute('UPDATE eppm.resource_pool SET capacity_fte=1 WHERE id=1')
    restricted = create_dashboard_service(path, access=editor)
    unrestricted = create_dashboard_service(path, access=manager)
    restricted.today = unrestricted.today = lambda: date(2026, 6, 1)
    assert restricted.consuming_projects([1], '2026-Q1') == [1]
    assert unrestricted.consuming_projects([1], '2026-Q1') == [1,2]
    assert restricted.consuming_projects([1], '2027-Q1') == []
    with pytest.raises(AccessDenied):
        restricted.consuming_projects([2], '2026-Q1')

