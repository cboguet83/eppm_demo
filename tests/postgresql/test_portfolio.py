"""Native bounded portfolio reads, exact facets and current scope enforcement."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, localcontext
from time import perf_counter
from threading import Event

import psycopg
from psycopg.types.json import Jsonb
import pytest

from app.application.exceptions import PortfolioRevisionChanged, ProjectStorageError
from app.application.services.portfolio import PortfolioService, portfolio_revision_token
from app.domain.access.models import AccessDenied
from app.infrastructure.postgresql.portfolio import PostgresPortfolioReader


COLUMNS = [
    {'key': 'name', 'format': 'text'}, {'key': 'project_template', 'format': 'text'},
    {'key': 'planned_budget', 'format': 'currency'},
    {'key': 'property:phase', 'param_id': 'phase', 'format': 'text'},
    {'key': 'property:number', 'param_id': 'number', 'format': 'number'},
    {'key': 'property:date', 'param_id': 'date', 'format': 'date'},
    {'key': 'property:tags', 'param_id': 'tags', 'format': 'text'},
]


def reader(authorized, user_id=4):
    return PostgresPortfolioReader(authorized.database, authorized.key, access=authorized.binding(user_id).access)


def service(authorized, user_id=4, allocations=None):
    return PortfolioService(reader(authorized, user_id), allocations)


@pytest.fixture
def portfolio(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(id,name) VALUES (2,'Special')")
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type,applies_to_all) "
                           "VALUES ('phase','Phase','TEXT',false),('number','Number','NUMBER',true),"
                           "('date','Date','DATE',true),('tags','Tags','TAGS',true)")
        connection.execute("INSERT INTO eppm.project_type_property(project_type_id,param_id) VALUES (2,'phase')")
        connection.execute("INSERT INTO eppm.project(id,name) SELECT id,'Project' FROM generate_series(4,255) id")
        connection.execute("UPDATE eppm.project SET name='Project ' || lpad(id::text,3,'0'),planned_budget=id,project_type_id=CASE WHEN id%2=1 THEN 2 ELSE 1 END")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) "
                           "SELECT id,'phase','text',CASE WHEN id>200 THEN 'Late' ELSE 'Early' END FROM eppm.project WHERE id%2=1")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,number_value) "
                           "SELECT id,'number','number',id+0.125 FROM eppm.project")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,date_value) VALUES (1,'date','date','2026-01-05')")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind) VALUES (1,'tags','list'),(2,'tags','list'),(2,'date','empty')")
        connection.execute("INSERT INTO eppm.project_property_value_item(project_id,param_id,position,value) VALUES (1,'tags',0,'Zed'),(1,'tags',1,'Alpha')")
    return authorized


def test_bounded_stable_pages_search_sort_and_exact_totals(portfolio):
    browse = service(portfolio)
    pages = [browse.get_page(COLUMNS, {}, offset) for offset in (0, 100, 200)]
    assert [len(page['rows']) for page in pages] == [100, 100, 55]
    assert [row['project_id'] for page in pages for row in page['rows']] == list(range(1, 256))
    assert all(page['total'] == 255 for page in pages)
    assert browse.get_page(COLUMNS, {}, 100000)['offset'] == 200
    assert browse.get_page(COLUMNS, {}, float('inf'))['offset'] == 0
    assert browse.get_page(COLUMNS, {'sort': {'column': 'planned_budget', 'direction': 'desc'}})['rows'][0]['project_id'] == 255
    assert browse.get_page(COLUMNS, {'sort': {'column': 'property:number', 'direction': 'desc'}})['rows'][0]['project_id'] == 255
    assert browse.get_page(COLUMNS, {'search': '255'})['rows'][0]['project_id'] == 255
    assert browse.get_page(COLUMNS, {'search': '%_" OR 1=1 --'})['total'] == 0
    assert browse.get_page(COLUMNS, {'sort': {'column': 'id; DROP TABLE project;'}})['total'] == 255
    metrics = browse.get_metrics()
    assert metrics.total_projects == 255 and metrics.total_planned == Decimal(32640)
    assert type(metrics.total_actual) is type(metrics.burn_rate) is Decimal


def test_facets_include_unloaded_projects_exclude_own_filter_and_bound_choices(portfolio):
    browse = service(portfolio)
    query = {'filters': {'property:phase': {'mode': 'include', 'values': ['Late']}}}
    page = browse.get_page(COLUMNS, query)
    assert page['total'] == 28 and page['rows'][0]['project_id'] == 201
    facet = browse.get_facet(COLUMNS, query, 'property:phase')
    assert dict(facet['stats']) == {'Rows': 255, 'Filled': 128, 'Unique': 2, 'Empty': 127, 'Most common': 'Early (100)'}
    assert {row['value']: row['count'] for row in facet['values']} == {'': 127, 'Early': 100, 'Late': 28}
    numeric = dict(browse.get_facet(COLUMNS, query, 'planned_budget')['stats'])
    assert (numeric['Minimum'], numeric['Average'], numeric['Maximum']) == (Decimal(201), Decimal(228), Decimal(255))
    names = browse.get_facet(COLUMNS, {}, 'name')
    assert len(names['values']) == 200 and names['has_more']
    assert browse.get_facet(COLUMNS, {}, 'name', '255')['values'] == [{'value': 'Project 255', 'count': 1}]
    assert browse.get_facet(COLUMNS, {'search': 'missing'}, 'name')['stats'] == [['Rows', 0], ['Filled', 0], ['Unique', 0], ['Empty', 0]]
    query = {'templates': ['General'], 'filters': {'planned_budget': {'mode': 'exclude', 'values': [2, 4]}}}
    assert browse.get_page(COLUMNS, query)['total'] == 125
    assert browse.get_page(COLUMNS, {'filters': {'property:phase': {'values': ['']}}})['total'] == 127
    assert browse.get_page(COLUMNS, {'filters': {'planned_budget': {'values': []}}})['total'] == 0
    assert browse.get_page(COLUMNS, {'filters': {'planned_budget': {'mode': 'exclude', 'values': []}}})['total'] == 255


def test_dynamic_property_kinds_applicability_and_date_style_are_preserved(portfolio):
    browse = service(portfolio)
    row = browse.get_page(COLUMNS, {'search': '001'})['rows'][0]
    assert row['property:number'] == Decimal('1.125') and type(row['property:number']) is Decimal
    assert row['property:date'] == '2026-01-05' and row['property:tags'] == 'Zed, Alpha'
    second = browse.get_page(COLUMNS, {'search': '002'})['rows'][0]
    assert second['property:date'] is second['property:tags'] is None
    before = browse.revision()
    portfolio.query('UPDATE eppm.project SET project_type_id=1 WHERE id=1', user_id=4, write=True)
    assert browse.revision() != before
    assert browse.get_page(COLUMNS, {'search': '001'})['rows'][0]['property:phase'] is None
    assert portfolio.query("SELECT text_value FROM eppm.project_property_value WHERE project_id=1 AND param_id='phase'") == [('Early',)]
    numeric = dict(browse.get_facet(COLUMNS, {}, 'property:number')['stats'])
    assert (numeric['Minimum'], numeric['Average'], numeric['Maximum']) == (Decimal('1.125'), Decimal('128.125'), Decimal('255.125'))


def test_scope_is_applied_before_counts_pages_facets_details_and_metrics(portfolio):
    browse = service(portfolio, 1)
    page = browse.get_page(COLUMNS, {}, 10000)
    assert page['total'] == 2 and [row['project_id'] for row in page['rows']] == [1, 2]
    assert browse.get_page(COLUMNS, {'search': '003'})['total'] == 0
    assert browse.get_facet(COLUMNS, {}, 'name')['values'] == [{'value': 'Project 001', 'count': 1}, {'value': 'Project 002', 'count': 1}]
    assert browse.get_metrics().total_planned == Decimal(3)
    assert browse.get_detail(3) is browse.get_detail(999) is None
    with pytest.raises(AccessDenied):
        service(portfolio, 3).get_page(COLUMNS, {})
    other = service(portfolio, 2)
    assert other.get_page(COLUMNS, {})['total'] == 1 and other.get_detail(3)['name'] == 'Project 003'


def test_numeric_facets_and_filters_preserve_exact_decimal_wire_values(portfolio):
    amount = Decimal('9007199254740993.01234567890123456789')
    with psycopg.connect(portfolio.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project SET planned_budget=%s,actual_budget=%s WHERE id=1', (amount, amount))
    browse = service(portfolio, 1)
    with localcontext() as context:
        context.prec = 4
        metrics = browse.get_metrics()
        assert str(metrics.total_planned) == '9007199254740995.01234567890123456789'
        assert metrics.variance == Decimal(2)
        stats = dict(browse.get_facet(COLUMNS, {}, 'planned_budget')['stats'])
        assert stats['Maximum'] == amount
        assert str(stats['Average']) == '4503599627370497.506172839450617283945'
    for value in (amount, str(amount)):
        page = browse.get_page(COLUMNS, {'filters': {'planned_budget': {'values': [value]}}})
        assert [row['project_id'] for row in page['rows']] == [1]
    assert type(browse.get_detail(1)['planned_budget']) is Decimal
    assert browse.get_page(COLUMNS, {'filters': {'property:number': {'values': ['1.125']}}})['total'] == 1
    assert browse.get_page(COLUMNS, {'filters': {'planned_budget': {'values': [None, {}, 'nan', 'inf', 'bad', float('nan')]}}})['total'] == 0


def test_untrusted_columns_and_values_never_become_executable_sql(portfolio):
    browse = service(portfolio)
    malicious = 'x";DROP TABLE eppm.project;--'
    columns = COLUMNS + [{'key': malicious, 'format': 'text', 'param_id': "phase' OR true--"}]
    assert browse.get_page(columns, {'filters': {malicious: {'values': ['']}}})['total'] == 255
    assert browse.get_page(columns, {'filters': {'name': {'values': [malicious]}}})['total'] == 0
    assert browse.get_page(columns, {'sort': {'column': malicious}})['rows'][0][malicious] is None
    assert browse.get_page(COLUMNS, {'filters': {'missing': {'values': []}, 'name': 'bad', 'status': {'values': {}}}})['total'] == 255
    assert browse.get_page(COLUMNS, {'filters': [], 'sort': [], 'templates': {}})['total'] == 255
    with pytest.raises(ValueError, match='Unknown portfolio column'):
        browse.get_facet(COLUMNS, {}, malicious)


def test_manager_labels_use_minimal_directory_and_bounded_reporting_ancestry(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level,manager_function_id) "
                           "VALUES (1,'Level three',3,NULL),(2,'Manager',4,1),(3,'Vacant',4,1),(4,'',4,1),(5,'Cycle A',5,NULL),(6,'Cycle B',4,5)")
        connection.execute('ALTER TABLE eppm.function DISABLE TRIGGER USER')
        connection.execute('UPDATE eppm.function SET manager_function_id=6 WHERE function_id=5')
        connection.execute('ALTER TABLE eppm.function ENABLE TRIGGER USER')
        connection.execute("INSERT INTO eppm.employee(firstname,lastname,email,employee_code,function_id) "
                           "VALUES (' Ada ','One','private@example.test','PRIVATE',2),('Zed','Zed','z@example.test','Z',2)")
        connection.execute('UPDATE eppm.project SET function_id=CASE id WHEN 1 THEN 2 WHEN 2 THEN 3 ELSE 5 END')
    browse = service(authorized, 1)
    row = browse.get_detail(1)
    assert row['project_manager'] == 'Ada  One' and row['level_3_manager_name'] == 'Level three'
    assert browse.get_detail(2)['project_manager'] == 'Vacant'
    assert service(authorized).get_detail(3)['level_3_manager_name'] == ''
    managers = browse.get_catalog().managers
    assert managers[2] == 'Ada One' and managers[3] == 'Vacant' and managers[4] == '—'
    assert browse.get_catalog(include_managers=False).managers == {}
    assert authorized.query('SELECT email FROM eppm.employee') == []
    assert 'private@example.test' not in repr(row) + repr(managers)


def test_page_and_count_share_a_read_only_snapshot_during_concurrent_insert(portfolio):
    entered, changed = Event(), Event()
    class PausedReader(PostgresPortfolioReader):
        def _run(self, operation):
            def paused(connection):
                assert connection.execute("SELECT current_setting('transaction_isolation'),current_setting('transaction_read_only')").fetchone() == ('repeatable read', 'on')
                # Authorization already established this transaction's snapshot.
                entered.set()
                assert changed.wait(10)
                return operation(connection)
            return super()._run(paused)
    paused = PausedReader(portfolio.database, portfolio.key, access=portfolio.binding(4).access)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(paused.get_page, COLUMNS, {}, 200)
        assert entered.wait(10)
        try:
            with psycopg.connect(portfolio.setup.operator_url) as connection:
                connection.execute("INSERT INTO eppm.project(id,name) VALUES (256,'Concurrent')")
        finally:
            changed.set()
        old = pending.result(timeout=10)
    assert old['total'] == 255 and len(old['rows']) == 55
    assert service(portfolio).get_page(COLUMNS, {}, 200)['total'] == 256


def test_revisions_and_deferred_badges_detect_hidden_and_current_security_changes(portfolio):
    calls = []
    def allocations(identities):
        calls.append(list(identities))
        return {identities[-1]} if identities else set()
    browse = service(portfolio, 1, allocations)
    page = browse.get_page(COLUMNS, {})
    assert calls == [[1, 2]] and [row['is_overallocated'] for row in page['rows']] == [False, True]
    before = browse.revision()
    assert browse.get_allocation_badges([1, 2], portfolio_revision_token(before))['overallocated'] == [2]
    portfolio.query("UPDATE eppm.project SET name='Hidden rename' WHERE id=3", user_id=4, write=True)
    assert browse.revision() == before
    portfolio.query("SELECT eppm.admin_grant(1,'project_viewer',%s)",
                    (Jsonb({'kind': 'projects', 'project_ids': [3]}),), user_id=5, write=True)
    with pytest.raises(PortfolioRevisionChanged):
        browse.get_allocation_badges([1, 2], portfolio_revision_token(before))
    assert browse.get_page(COLUMNS, {})['total'] == 3
    with psycopg.connect(portfolio.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.app_session SET revoked=true WHERE session_hash='session-1'")
    with pytest.raises(AccessDenied):
        browse.revision()


def test_catalog_reads_current_groups_properties_and_options_in_stable_order(portfolio):
    with psycopg.connect(portfolio.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.schema_groups(id,group_name,display_order) VALUES (1,'Second',2),(2,'First',1)")
        connection.execute("INSERT INTO eppm.schema_param_options(param_id,option_value,display_order) VALUES ('phase','Second',2),('phase','First',1)")
    catalog = service(portfolio, 1).get_catalog(include_managers=False)
    assert [group['group_name'] for group in catalog.groups] == ['First', 'Second']
    assert [option['option_value'] for option in catalog.options] == ['First', 'Second']
    assert [prop['param_id'] for prop in catalog.parameters] == ['date', 'number', 'phase', 'tags']
    assert catalog.parameters[2]['applies_to_all'] is False


def test_storage_outage_is_safe_and_never_returns_a_cached_scope(portfolio, caplog):
    browse = service(portfolio)
    browse.revision()
    portfolio.database.close()
    with pytest.raises(ProjectStorageError, match='could not be accessed') as failure:
        browse.get_detail(1)
    assert 'postgresql://' not in str(failure.value) + caplog.text


def test_numeric_zero_nulls_and_case_insensitive_order_match_existing_grid(portfolio):
    with psycopg.connect(portfolio.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name=CASE id WHEN 1 THEN 'zebra' WHEN 2 THEN 'Alpha' ELSE 'alpha' END,"
                           'planned_budget=CASE id WHEN 1 THEN NULL WHEN 2 THEN 0 ELSE 10 END WHERE id<=3')
        connection.execute("UPDATE eppm.project_property_value SET number_value=0 WHERE project_id=1 AND param_id='number'")
    browse = service(portfolio, 1)
    assert [row['project_id'] for row in browse.get_page(COLUMNS, {'sort': {'column': 'planned_budget'}})['rows']] == [1, 2]
    assert [row['project_id'] for row in browse.get_page(COLUMNS, {'sort': {'column': 'planned_budget', 'direction': 'desc'}})['rows']] == [2, 1]
    assert browse.get_page(COLUMNS, {'search': 'ALPHA'})['rows'][0]['project_id'] == 2
    assert browse.get_page(COLUMNS, {'filters': {'planned_budget': {'values': ['']}}})['rows'][0]['project_id'] == 1
    assert browse.get_page(COLUMNS, {'filters': {'planned_budget': {'values': [False]}}})['rows'][0]['project_id'] == 2
    assert type(browse.get_page(COLUMNS, {'search': 'zebra'})['rows'][0]['property:number']) is Decimal
    stats = dict(browse.get_facet(COLUMNS, {}, 'planned_budget')['stats'])
    assert stats['Empty'] == 1 and stats['Minimum'] == stats['Average'] == stats['Maximum'] == Decimal(0)
    admin = service(portfolio)
    filtered = {'filters': {'project_id': {'values': [1, 2, 3]}}, 'sort': {'column': 'name'}}
    assert [row['project_id'] for row in admin.get_page(COLUMNS, filtered)['rows']] == [2, 3, 1]


def test_missing_display_metadata_keeps_text_facet_contract_and_json_parsing_is_cursor_local(portfolio):
    browse = service(portfolio, 1)
    browse.get_page(COLUMNS, {})
    facet = browse.get_facet([], {}, 'planned_budget')
    assert facet['format'] == 'text' and dict(facet['stats'])['Most common'] == '1 (1)'
    assert type(portfolio.query('SELECT %s::jsonb', (Jsonb({'value': 1.5}),))[0][0]['value']) is float
    assert browse.revision()


def test_large_portfolio_keeps_pages_and_facets_bounded_without_hydrating_all_values(portfolio, record_property):
    with psycopg.connect(portfolio.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name,planned_budget) SELECT id,'Large ' || id,id FROM generate_series(256,10001) id")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,number_value) "
                           "SELECT id,'number','number',id+0.125 FROM eppm.project WHERE id>255")
    browse = service(portfolio)
    started = perf_counter()
    first = browse.get_page(COLUMNS, {})
    first_elapsed = perf_counter() - started
    started_last = perf_counter()
    last = browse.get_page(COLUMNS, {}, 10000)
    last_elapsed = perf_counter() - started_last
    started_facet = perf_counter()
    numeric = browse.get_facet(COLUMNS, {}, 'property:number')
    record_property('native_portfolio_first_page_seconds', round(first_elapsed, 4))
    record_property('native_portfolio_last_page_seconds', round(last_elapsed, 4))
    record_property('native_portfolio_facet_seconds', round(perf_counter() - started_facet, 4))
    record_property('native_portfolio_three_reads_seconds', round(perf_counter() - started, 4))
    assert first['total'] == last['total'] == 10001
    assert len(first['rows']) == 100 and [row['project_id'] for row in last['rows']] == [10001]
    assert len(numeric['values']) == 200 and numeric['has_more']
    assert dict(numeric['stats'])['Maximum'] == Decimal('10001.125')
