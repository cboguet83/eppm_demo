"""Independent demand/calendar parity at the dashboard's private SQL boundary."""

from tests.postgresql.plan_fixtures import seed_test_plans
from datetime import date, timedelta
import random

import psycopg
import pytest

from app.domain.dashboard import quarterly_capacity, quarterly_shortfall
from app.infrastructure.postgresql.migration import MIGRATION_DIRECTORY
from tests.postgresql.test_dashboard import DAY, reference_details, service
from tests.postgresql.test_pool_capacity import staffing


@pytest.fixture(autouse=True)
def daily_baseline(staffing):
    """Install the previous implementation only in the isolated test database."""
    source = MIGRATION_DIRECTORY / '0035_dashboard_pool_availability.sql'
    with psycopg.connect(staffing.setup.operator_url) as connection:
        baseline = source.read_text().replace(
            'eppm.dashboard_resource_breakdown', 'eppm.dashboard_resource_breakdown_daily_baseline')
        connection.execute(baseline.replace(' AS $$', ' SET jit = off AS $$'))


def assert_resources_match_domain(authorized, selected, day=DAY):
    for quarter, pool, metric in ((None, None, 'overallocation'),
                                  ('2026-Q1', None, 'allocation'),
                                  ('2026-Q2', None, 'overallocation')):
        args = (selected, day, quarter, pool, metric)
        current = authorized.query('SELECT eppm.dashboard_resource_breakdown(%s,%s,%s,%s,%s)', args, user_id=4)
        baseline = authorized.query('SELECT eppm.dashboard_resource_breakdown_daily_baseline(%s,%s,%s,%s,%s)', args, user_id=4)
        current[0][0].pop('overallocated_pools')
        assert current == baseline
    expected = reference_details(authorized, selected, day)
    actual = service(authorized, 4, lambda: day).resources(selected)
    assert actual == {'overallocation': quarterly_shortfall(expected, set(selected), day.year),
                      'capacity': quarterly_capacity(expected, day.year)}
    return actual


def test_pool_reductions_apply_only_to_unstaffed_pools_and_match_dashboard(staffing):
    """Mapped pools use employee calendars; unmapped pools use pool reductions."""
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.resource_pool_capacity_exception
            (pool_id,start_date,end_date,reduction_fte) VALUES
            (1,'2026-01-01','2026-06-30',.5),
            (1,'2026-02-01','2026-03-03',.25),
            (2,'2026-01-01','2026-12-31',20)""")
    assert_resources_match_domain(staffing, [1, 2])


def test_relative_demand_matches_domain_after_owner_dates_cross_quarters(staffing):
    """Dashboard and capacity resolve start/end origins on every current snapshot."""
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.resource_pool_assignment')
        connection.execute("UPDATE eppm.project_task SET start_date='2026-03-25',end_date='2026-03-31' WHERE project_id=1")
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned,schedule_anchor,offset_days,duration_days,project_plan_id) VALUES (1,1,1,20,'start',10,5,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(2,1,NULL,20,'end',10,5,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))")
    report = assert_resources_match_domain(staffing, [1])
    assert report['overallocation']['2026-Q1'] == 0
    assert report['overallocation']['2026-Q2'] > 0
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project_task SET start_date=start_date+100,end_date=end_date+100 WHERE project_id=1")
    report = assert_resources_match_domain(staffing, [1])
    assert report['overallocation']['2026-Q2'] == 0
    assert report['overallocation']['2026-Q3'] > 0


def test_randomized_overlapping_project_and_task_demand_keeps_float_rounding_order(staffing):
    rng = random.Random(42)
    choices = [0, 0.0005, 0.0035, 0.0105, 0.3333, 1.0005, 1.125, 2.2222, 20.1235]
    first = date(2026, 3, 20)
    for iteration in range(20):
        with psycopg.connect(staffing.setup.operator_url) as connection:
            connection.execute('DELETE FROM eppm.resource_pool_assignment')
            for pool in range(1, 6):
                connection.execute('UPDATE eppm.resource_pool SET capacity_fte=%s WHERE id=%s',
                                   (rng.choice(choices), pool))
                for project in range(1, 4):
                    for task in (None, project):
                        start = first + timedelta(days=rng.randrange(12))
                        end = start + timedelta(days=rng.randrange(12))
                        connection.execute('''INSERT INTO eppm.resource_pool_assignment
                            (pool_id,project_id,task_id,fte_assigned,start_date,end_date,project_plan_id)
                            VALUES (%s,%s,%s,%s,%s,%s,(SELECT id FROM eppm.project_plan WHERE project_id=%s AND is_current))''', (pool, project, task, rng.choice(choices), start, end, project))
        selected = [1] if iteration % 2 else [1, 2]
        assert_resources_match_domain(staffing, selected)


def test_calendar_peaks_are_concurrent_and_full_quarter_overrides_replace_baselines(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.resource_pool_assignment')
        connection.execute('DELETE FROM eppm.resource_pool_mapping')
        connection.execute('DELETE FROM eppm.employee_calendar_exception')
        connection.execute("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) "
                           "VALUES (1,'employee',1,100),(2,'employee',4,100)")
        connection.execute('UPDATE eppm.employee SET occupation_percentage=20 WHERE employee_id IN (1,4)')
        connection.execute('''INSERT INTO eppm.employee_calendar_exception
            (employee_id,start_date,end_date,occupation_percentage) VALUES
            (1,'2026-01-01','2026-01-01',100),(4,'2026-02-01','2026-02-01',100),
            (1,'2026-04-01','2026-06-30',0),(4,'2026-04-01','2026-06-30',0)''')
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date,project_plan_id) VALUES (1,1,2,'2026-01-01','2026-06-30',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(2,1,3,'2026-01-01','2026-06-30',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))")
    actual = assert_resources_match_domain(staffing, [1])
    assert actual['capacity']['2026-Q1'] == 1.2
    assert actual['capacity']['2026-Q2'] == 0
    assert actual['capacity']['2026-Q3'] == 0.4
    assert actual['overallocation']['2026-Q2'] == 5


def test_undated_custom_partial_and_quarter_boundary_periods_keep_the_current_day_fallback(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name) VALUES (4,'Undated')")
        seed_test_plans(connection)
        connection.execute('DELETE FROM eppm.resource_pool_assignment')
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date,project_plan_id) VALUES (2,4,3,NULL,NULL,(SELECT id FROM eppm.project_plan WHERE project_id=4 AND is_current)),(5,4,1,'2026-09-30',NULL,(SELECT id FROM eppm.project_plan WHERE project_id=4 AND is_current)),(4,4,1,NULL,'2026-10-01',(SELECT id FROM eppm.project_plan WHERE project_id=4 AND is_current))")
    dashboard = service(staffing, 4, lambda: date(2026, 9, 30))
    before = dashboard.revision()
    september = assert_resources_match_domain(staffing, [4], date(2026, 9, 30))
    october = assert_resources_match_domain(staffing, [4], date(2026, 10, 1))
    assert september['overallocation']['2026-Q3'] > october['overallocation']['2026-Q3']
    assert october['overallocation']['2026-Q4'] > september['overallocation']['2026-Q4']
    dashboard.today = lambda: date(2026, 10, 1)
    assert dashboard.revision() != before


def test_long_periods_keep_the_25_year_demand_cap_and_displayed_window(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.resource_pool_assignment')
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date,project_plan_id) VALUES (5,1,2,'2000-01-01','2099-12-31',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(5,3,30,'2000-01-01','2099-12-31',(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))")
    actual = assert_resources_match_domain(staffing, [1])
    assert actual['overallocation']['2024-Q4'] == 32
    assert actual['overallocation']['2025-Q1'] == actual['overallocation']['2026-Q1'] == 0
    assert len(actual['overallocation']) == 80


def test_partial_period_resolving_backwards_does_not_invent_selected_consuming_days(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.resource_pool_assignment')
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned,start_date,end_date,project_plan_id) VALUES (5,1,1,3,'2026-01-10',NULL,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(5,3,3,30,'2026-01-10','2026-01-10',(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))")
    actual = assert_resources_match_domain(staffing, [1])
    assert all(value == 0 for value in actual['overallocation'].values())
    assert service(staffing).consuming_projects([1], '2026-Q1') == []


def test_revision_and_resources_are_read_only_and_never_return_private_records(staffing):
    def revisions(connection):
        return tuple(connection.execute('SELECT project_id,generation,revision FROM eppm.project_cache_revision ORDER BY project_id'))
    with psycopg.connect(staffing.setup.operator_url) as connection:
        before = revisions(connection)
    for user in (1, 4):
        result = staffing.query('SELECT eppm.dashboard_resources(%s::bigint[],%s,%s)', ([1], DAY, '2026-Q1'), user_id=user)[0][0]
        assert set(result) == {'capacity', 'overallocation', 'consumers'}
        assert all(isinstance(value, (int, float)) for series in ('capacity', 'overallocation') for value in result[series].values())
        assert not any(value in repr(result) for value in ('Private', 'Hidden', 'Ada', 'employee_id', 'session-'))
        assert service(staffing, user).revision()
    with psycopg.connect(staffing.setup.operator_url) as connection:
        assert revisions(connection) == before


@pytest.mark.parametrize('table, condition', [
    ('pool_cache_revision', 'pool_id=1'), ('catalog_cache_revision', 'singleton'),
    ('database_identity', 'singleton'),
])
def test_missing_required_revision_sources_fail_closed(staffing, table, condition):
    from psycopg import sql
    from app.application.exceptions import ProjectStorageError

    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute(sql.SQL('DELETE FROM eppm.{} WHERE ').format(sql.Identifier(table)) + sql.SQL(condition))
    with pytest.raises(ProjectStorageError):
        service(staffing).revision()


def test_change_points_preserve_concurrent_pools_quarter_ties_and_leap_day(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.resource_pool_assignment')
        connection.execute('DELETE FROM eppm.resource_pool_mapping')
        connection.execute('UPDATE eppm.resource_pool SET capacity_fte=5')
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date,project_plan_id) VALUES (1,1,4,'2023-12-01','2024-06-30',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(2,1,3,'2024-02-29','2024-03-01',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(1,3,2,'2024-02-29','2024-02-29',(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))")
        connection.execute("""INSERT INTO eppm.resource_pool_capacity_exception
            (pool_id,start_date,end_date,reduction_fte) VALUES
            (1,'2024-02-29','2024-02-29',2)""")
    args = ([1], date(2024, 1, 1), '2024-Q1', 1, 'overallocation')
    current = staffing.query('SELECT eppm.dashboard_resource_breakdown(%s,%s,%s,%s,%s)', args)[0][0]
    baseline = staffing.query('SELECT eppm.dashboard_resource_breakdown_daily_baseline(%s,%s,%s,%s,%s)', args)[0][0]
    current.pop('overallocated_pools')
    assert current == baseline
    assert current['allocation']['2024-Q1'] == 9
    assert current['overallocation']['2024-Q1'] == 3
    assert current['peak_days']['allocation']['2024-Q1'] == '2024-02-29'
    assert current['peak_days']['allocation']['2024-Q2'] == '2024-04-01'
    assert current['consumers'] == [1]
    assert sum(pool['allocation']['2024-Q1'] for pool in current['pools']) == 9
    assert staffing.query("SELECT eppm.dashboard_resource_breakdown(%s,%s) - 'overallocated_pools'", ([], date(2024, 1, 1))) == staffing.query(
        'SELECT eppm.dashboard_resource_breakdown_daily_baseline(%s,%s)', ([], date(2024, 1, 1)))


def test_warning_lists_all_overallocated_pools_not_just_the_total_peak(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.resource_pool_assignment')
        connection.execute('DELETE FROM eppm.resource_pool_mapping')
        connection.execute('UPDATE eppm.resource_pool SET capacity_fte=1')
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date,project_plan_id) VALUES (1,1,10,'2026-01-01','2026-01-01',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(2,1,2,'2026-02-01','2026-02-01',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(3,1,.5,'2026-02-01','2026-02-01',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(4,3,20,'2026-02-01','2026-02-01',(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current)),(5,1,20,'2020-02-01','2020-02-01',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current))")
    report = staffing.query('SELECT eppm.dashboard_resource_breakdown(%s,%s)', ([1], DAY))[0][0]
    assert {pool['pool_id'] for pool in report['overallocated_pools']} == {1, 2}
    assert all(set(pool) == {'pool_id', 'name'} for pool in report['overallocated_pools'])
    assert next(pool for pool in report['pools'] if pool['pool_id'] == 2)['overallocation']['2026-Q1'] == 0
    assert staffing.query('SELECT eppm.dashboard_resource_breakdown(%s,%s)', ([], DAY))[0][0]['overallocated_pools'] == []
