"""Native dashboard scope, exact reports and aggregate-only competing demand."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Event

import psycopg
import pytest

from app.application.exceptions import ProjectStorageError
from app.application.services.dashboard import DashboardService
from app.application.services.finance import FinanceService
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, DeploymentActor
from app.domain.dashboard import quarterly_capacity, quarterly_shortfall, quarter_bounds, responsible_pools
from app.domain.resources.capacity import calculate_capacity
from app.infrastructure.postgresql.dashboard import PostgresDashboardReader
from app.infrastructure.postgresql.finance import PostgresFinanceGateway
from tests.postgresql.test_pool_capacity import staffing, reference_inputs


DAY = date(2026, 1, 3)


def reader(authorized, user_id=1):
    return PostgresDashboardReader(authorized.database, authorized.key, access=authorized.binding(user_id).access)


def service(authorized, user_id=1, today=lambda: DAY):
    return DashboardService(reader(authorized, user_id), today)


def reference_details(authorized, project_ids, today=DAY):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        pools = [row[0] for row in connection.execute('SELECT DISTINCT pool_id FROM eppm.resource_pool_assignment '
            'WHERE project_id=ANY(%s::bigint[]) AND fte_assigned>0 ORDER BY pool_id', (project_ids,))]
    return [calculate_capacity(values, today) for values in reference_inputs(authorized, pools).values()]


def test_private_competing_demand_and_calendars_match_the_existing_domain_aggregates(staffing):
    restricted = service(staffing)
    expected = reference_details(staffing, [1])
    actual = restricted.resources([1])
    assert actual == {'overallocation': quarterly_shortfall(expected, {1}, DAY.year),
                      'capacity': quarterly_capacity(expected, DAY.year)}
    assert restricted.shortages([1]) == actual['overallocation']
    assert actual['overallocation']['2026-Q1'] == 19.985  # Includes hidden project 3's competing demand.
    assert len(actual['overallocation']) == len(actual['capacity']) == 80
    assert set(actual) == {'overallocation', 'capacity'}
    start, end = quarter_bounds('2026-Q1', DAY.year)
    pools = responsible_pools(expected, {1}, start, end)
    expected_ids = sorted({row['project_id'] for pool in expected if pool.pool_id in pools for row in pool.assignments
                          if row['project_id'] in {1, 2} and row['fte_assigned'] > 0
                          and row['start_date'] <= end.isoformat() and row['end_date'] >= start.isoformat()})
    assert restricted.consuming_projects([1], '2026-Q1') == expected_ids
    assert service(staffing, 4).consuming_projects([1], '2026-Q1') == [1, 2, 3]
    assert restricted.consuming_projects([1], '2027-Q1') == []


def test_empty_scope_and_no_business_grants_preserve_empty_dashboard_behavior(staffing):
    empty = service(staffing, 3)
    assert empty.catalog().projects == [] and empty.catalog().parameters == []
    assert empty.report([]).approved is None and empty.report([]).issue_count == 0
    assert empty.revision() and empty.issues([], 'en') == []
    assert all(value == 0.0 for values in empty.resources([]).values() for value in values.values())
    assert empty.consuming_projects([], '2026-Q1') == []
    with pytest.raises(AccessDenied):
        empty.report([1])


@pytest.mark.parametrize('requested', [[3], [1, 3], [True], ['1'], [999], [None]])
def test_every_explicit_dashboard_read_requires_current_read_scope(staffing, requested):
    dashboard = service(staffing)
    for operation in (lambda: dashboard.report(requested), lambda: dashboard.resources(requested),
                      lambda: dashboard.issues(requested, 'en'), lambda: dashboard.consuming_projects(requested, '2026-Q1')):
        with pytest.raises(AccessDenied):
            operation()


def test_sql_aggregate_boundary_reauthorizes_direct_runtime_calls(staffing):
    for ids in ([3], [1, 3], [None], None):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            staffing.query('SELECT eppm.dashboard_resources(%s::bigint[],%s)', (ids, DAY))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        staffing.database.run(lambda connection: connection.execute('SELECT eppm.dashboard_revision()').fetchone())
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        staffing.database.run(lambda connection: connection.execute('SELECT eppm.dashboard_resources(%s::bigint[],%s)', ([1], DAY)).fetchone())
    for day, quarter in ((None, None), (DAY, '2026-Q5'), (DAY, '2041-Q1')):
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            staffing.query('SELECT eppm.dashboard_resources(%s::bigint[],%s,%s)', ([1], day, quarter))
    with pytest.raises(ValueError, match='Select a quarter'):
        service(staffing).consuming_projects([1], '2026-Q5')


def test_reports_use_requested_latest_finance_status_exact_shares_and_localized_blockers(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.wbs(id,code) VALUES (1,'A')")
        connection.execute('INSERT INTO eppm.project_wbs(project_id,wbs_id,percentage) VALUES (1,1,50),(3,1,50)')
        blocker = connection.execute("INSERT INTO eppm.project_event_type(name,system_code) "
                                     "VALUES ('Blocking point','blocking_point') RETURNING id").fetchone()[0]
        connection.execute("INSERT INTO eppm.project_log_event(project_id,title,event_type_id,status,deadline) "
                           "VALUES (1,'Visible blocker',%s,'active','2026-01-20'),(3,'Hidden blocker',%s,'active',NULL),"
                           "(1,'Closed blocker',%s,'closed',NULL)", (blocker, blocker, blocker))
        connection.execute('INSERT INTO eppm.project_event_type_translation(catalog_id,locale,label) VALUES (%s,%s,%s) '
                           'ON CONFLICT(catalog_id,locale) DO UPDATE SET label=excluded.label', (blocker, 'fr', 'Blocage'))
    access = staffing.binding(4).access
    finance = FinanceService(PostgresFinanceGateway(staffing.database, staffing.key, access=access))
    finance.today = lambda: DAY
    first = finance.save([{'code': 'A', 'amounts': {'2026': '1.01'}}], base_id=None, name='Approved', status='Approved', year=2026)
    newer = finance.save([{'code': 'A', 'amounts': {'2026': '2.01'}}], base_id=first, name='Newer', status='Approved', year=2026)
    finance.save([{'code': 'A', 'amounts': {'2026': '6.01'}}], base_id=newer, name='Draft', status='Draft', year=2026)
    dashboard = service(staffing)
    assert dashboard.report([1]).budget.totals == {2026: Decimal('1.01')}
    assert dashboard.report([1], 'Draft').budget.totals == {2026: Decimal('3.01')}
    assert dashboard.report([1], 'Proposed').approved is None
    assert dashboard.report([1]).issue_count == 1
    event, = dashboard.issues([1], 'fr')
    assert (event['title'], event['deadline'], event['event_type']) == ('Visible blocker', '2026-01-20', 'Blocage')
    assert isinstance(event['created_at'], str)
    before = dashboard.revision()
    finance.cancel(newer)
    assert dashboard.revision() != before and dashboard.report([1]).budget.totals == {2026: Decimal('0.51')}
    with pytest.raises(ValueError, match='Select Approved'):
        dashboard.report([1], 'Canceled')


def test_revision_is_opaque_actor_scoped_and_tracks_only_relevant_competing_sources(staffing):
    dashboard = service(staffing)
    before = dashboard.revision()
    assert len(before[0]) == 64 and 'session-1' not in repr(before)
    assert service(staffing, 2).revision() != before
    staffing.query('SELECT eppm.session_activity()', write=True)
    assert dashboard.revision() == before
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name) VALUES (4,'Unrelated hidden')")
        connection.execute("INSERT INTO eppm.resource_pool(id,name) VALUES (7,'Other hidden pool')")
        connection.execute('INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned) VALUES (7,4,1)')
    assert dashboard.revision() == before
    staffing.query('UPDATE eppm.resource_pool_assignment SET fte_assigned=21 WHERE project_id=3 AND pool_id=1', user_id=4, write=True)
    assert dashboard.revision() != before
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.app_session SET revoked=true WHERE session_hash='session-1'")
    with pytest.raises(AccessDenied):
        dashboard.catalog()
    with pytest.raises(AccessDenied):
        dashboard.revision()


def test_catalog_keeps_current_applicability_labels_lists_tags_and_active_projects(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project SET function_id=3 WHERE id IN (1,3)')
        connection.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES (1,3),(2,3)')
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type,applies_to_all) "
                           "VALUES ('text','Text','TEXT',true),('n','Number','NUMBER',true),('d','Date','DATE',true),"
                           "('tags','Tags','TAGS',true),('inactive','Inactive','TEXT',false),('manager','Override','TAGS',true)")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value,number_value,date_value) VALUES "
                           "(1,'text','text','Visible value',NULL,NULL),(1,'n','number',NULL,1.125,NULL),"
                           "(1,'d','date',NULL,NULL,'2026-01-05'),(1,'inactive','text','Never shown',NULL,NULL),"
                           "(1,'tags','list',NULL,NULL,NULL),(2,'tags','list',NULL,NULL,NULL),(2,'manager','list',NULL,NULL,NULL)")
        connection.execute("INSERT INTO eppm.project_property_value_item(project_id,param_id,position,value) "
                           "VALUES (1,'tags',0,'Zed'),(1,'tags',1,'Alpha'),(2,'manager',0,'Override')")
        connection.execute("INSERT INTO eppm.schema_parameter_translation(param_id,locale,alias) VALUES ('text','fr','Texte')")
        connection.execute("INSERT INTO eppm.tag_dictionnary(id,tag) VALUES (1,'Selected'),(2,'Hidden tag')")
        connection.execute('INSERT INTO eppm.project_tag(project_id,tag_id) VALUES (1,1),(3,2)')
    dashboard = service(staffing)
    catalog = dashboard.catalog()
    first, second = catalog.projects
    assert first['fields']['team'] == ['1', '2'] and first['fields']['project_manager'] == ['Cara Three']
    assert first['fields']['text'] == ['Visible value'] and first['fields']['n'] == ['1.125']
    assert first['fields']['d'] == ['2026-01-05'] and first['fields']['tags'] == ['Zed', 'Alpha']
    assert first['fields']['_project_tags'] == ['Selected'] and 'inactive' not in first['fields']
    assert second['fields']['tags'] == [] and second['fields']['manager'] == ['Override']
    assert next(row for row in catalog.parameters if row['param_id'] == 'text')['translations'] == {'fr': 'Texte'}
    assert all('Hidden tag' not in str(values) for values in catalog.labels.values())
    staffing.query("UPDATE eppm.project SET status=' Completed ' WHERE id=2", user_id=4, write=True)
    assert [row['id'] for row in dashboard.catalog().projects] == [1]
    with psycopg.connect(staffing.setup.operator_url) as connection:
        grants = connection.execute('SELECT id FROM eppm.app_role_assignment WHERE user_id=1').fetchall()
    for grant, in grants:
        staffing.query('SELECT eppm.admin_revoke(%s)', (grant,), user_id=5, write=True)
    assert dashboard.catalog().projects == []


def test_resources_retain_repeatable_read_snapshot_during_a_competing_save(staffing):
    entered, changed = Event(), Event()
    before = service(staffing).resources([1])
    class PausedReader(PostgresDashboardReader):
        def _run(self, operation, requested=None):
            def pause(connection, ids, security):
                assert connection.execute("SELECT current_setting('transaction_isolation'),current_setting('transaction_read_only')").fetchone() == ('repeatable read', 'on')
                entered.set()
                assert changed.wait(10)
                return operation(connection, ids, security)
            return super()._run(pause, requested)
    paused = PausedReader(staffing.database, staffing.key, access=staffing.binding().access)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(paused.resources, [1], DAY)
        assert entered.wait(10)
        try:
            staffing.query('UPDATE eppm.resource_pool_assignment SET fte_assigned=100 WHERE project_id=3', user_id=4, write=True)
        finally:
            changed.set()
        assert pending.result(timeout=10) == before
    assert service(staffing).resources([1]) != before


def test_missing_revision_metadata_and_storage_outage_fail_safely(staffing, caplog):
    dashboard = service(staffing)
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.project_cache_revision WHERE project_id=3')
    with pytest.raises(ProjectStorageError, match='Please try again'):
        dashboard.revision()
    staffing.database.close()
    with pytest.raises(ProjectStorageError, match='Please try again'):
        dashboard.catalog()
    assert 'postgresql://' not in caplog.text


def test_dashboard_rejects_operator_actors_and_invalid_transaction_signatures(staffing):
    access = staffing.binding().access
    for binding, key in ((BusinessAccess(DeploymentActor('test setup', 'dashboard-check'), access.policy), staffing.key),
                         (access, b'x' * 32)):
        invalid = PostgresDashboardReader(staffing.database, key, access=binding)
        with pytest.raises(AccessDenied):
            invalid.catalog()


def test_catalog_hierarchy_and_duplicate_labels_keep_only_current_project_facets(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        for identity in range(6, 10):
            connection.execute('INSERT INTO eppm.function(function_id,name,hierarchy_level,manager_function_id) '
                               'VALUES (%s,%s,%s,%s)', (identity, f'Role {identity}', identity - 3,
                                                       identity - 1 if identity > 6 else None))
            connection.execute('INSERT INTO eppm.employee(employee_id,firstname,lastname,email,employee_code,function_id) '
                               'VALUES (%s,%s,%s,%s,%s,%s)', (identity, 'Same', 'Name', f'{identity}@example.test',
                                                            str(identity), identity))
        connection.execute('UPDATE eppm.project SET function_id=8 WHERE id=1')
        connection.execute('UPDATE eppm.project SET function_id=9 WHERE id IN (2,3)')
    dashboard = service(staffing)
    catalog = dashboard.catalog()
    assert catalog.projects[0]['fields']['level3'] == ['6']
    assert catalog.projects[0]['fields']['level4'] == ['7']
    assert catalog.labels['manager'] == {'8': 'Same Name (Role 8, #8)', '9': 'Same Name (Role 9, #9)'}
    assert catalog.labels['level3'] == {'6': 'Same Name (Role 6, #6)'}
    assert dashboard.choices(catalog, {'manager': ['8', '6']}, 'manager') == ['8', '9']
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.function SET manager_function_id=8 WHERE function_id=7')
    assert dashboard.catalog().projects[0]['fields']['level3'] == ['']
