"""Overlapping absolute reductions, native authorization and chart parity."""

from dataclasses import replace
from datetime import date
from unittest.mock import patch

import pandas as pd

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from app.domain.access.models import AccessDenied
from app.domain.resources.models import PoolCapacityException, ResourcePool, PoolAssignment
from app.domain.resources.capacity import calculate_capacity
from app.infrastructure.postgresql.operator_capacity import read_operator_capacity_inputs
from tests.postgresql.test_resource_pools import pools, service


def test_overlapping_reductions_match_native_calendar_and_invalidate_revisions(authorized, pools):
    identity = pools.create_pool(ResourcePool('Exceptions', capacity_fte=5))
    before = authorized.query('SELECT eppm.display_cache_revisions()')
    first = pools.save_capacity_exception(PoolCapacityException(identity, '2026-01-01', '2026-03-03', .5))
    second = pools.save_capacity_exception(PoolCapacityException(identity, '2026-02-01', '2026-11-05', .25))
    assert authorized.query('SELECT eppm.display_cache_revisions()') != before
    with psycopg.connect(authorized.setup.operator_url) as connection:
        inputs = read_operator_capacity_inputs(connection, [identity])[identity]
        detail = calculate_capacity(inputs, date(2026, 1, 1))
    native = authorized.query('SELECT calendar FROM eppm.pool_effective_capacity(%s)', ([identity],))[0][0]
    assert native == detail.capacity_calendar
    assert native['2026-01-01'] == 4.5
    assert native['2026-02-01'] == native['2026-03-03'] == 4.25
    assert native['2026-03-04'] == native['2026-11-05'] == 4.75
    assert '2026-11-06' not in native
    item = next(item for item in pools.capacity_exceptions(identity) if item.id == first)
    pools.save_capacity_exception(replace(item, reduction_fte=9))
    assert authorized.query('SELECT calendar FROM eppm.pool_effective_capacity(%s)', ([identity],))[0][0]['2026-02-01'] == 0
    assert pools.delete_capacity_exception(first)
    assert pools.delete_capacity_exception(second)


def test_exception_writes_require_shared_admin_and_validate_ranges(authorized, pools):
    identity = pools.create_pool(ResourcePool('Guarded', capacity_fte=5))
    item = PoolCapacityException(identity, '2026-01-01', '2026-02-01', .5)
    with pytest.raises(AccessDenied):
        service(authorized, 1).save_capacity_exception(item)
    for change in (dict(end_date='2025-12-31'), dict(reduction_fte=-1), dict(reduction_fte=float('nan'))):
        with pytest.raises(ValueError):
            pools.save_capacity_exception(replace(item, **change))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute("INSERT INTO eppm.resource_pool_capacity_exception(pool_id,start_date,end_date,reduction_fte) VALUES (%s,'2026-02-01','2026-01-01',.5)",(identity,))


def exception_app(service, identity):
    from app.presentation.components.resource_pool_dialogs import _capacity_exceptions_editor
    _capacity_exceptions_editor(service, identity)


def test_exception_editor_saves_a_native_reduction(pools):
    identity = pools.create_pool(ResourcePool('Editor', capacity_fte=5))
    app = AppTest.from_function(exception_app, args=(pools, identity), default_timeout=10).run()
    edited = pd.DataFrame([{'id': None, 'Start date': date(2026, 1, 1),
        'End date': date(2026, 3, 3), 'Capacity reduction (FTE)': .5, 'Reason': 'Training'}])
    with patch('streamlit.data_editor', return_value=edited):
        app.button(key=f'pool_exception_grid_save_{identity}').click().run()
    assert not app.exception
    assert len(pools.capacity_exceptions(identity)) == 1


def test_dashboard_stacks_sum_to_total_and_pool_drillthrough_is_scoped(authorized, pools):
    one = pools.create_pool(ResourcePool('Pool one', capacity_fte=1))
    two = pools.create_pool(ResourcePool('Pool two', capacity_fte=2))
    pools.create_assignment(PoolAssignment(one,1,4,start_date='2026-01-01',end_date='2026-01-31'))
    pools.create_assignment(PoolAssignment(two,2,7,start_date='2026-01-01',end_date='2026-01-31'))
    pools.save_capacity_exception(PoolCapacityException(one,'2026-01-01','2026-01-31',.5))
    report = authorized.query('SELECT eppm.dashboard_resource_breakdown(%s,%s)',([1,2],date(2026,1,1)))[0][0]
    assert report['allocation']['2026-Q1'] == 11
    assert report['overallocation']['2026-Q1'] == 8.5
    availability = {pool['pool_id']: pool['available']['2026-Q1'] for pool in report['pools']}
    assert availability == {one: -3.5, two: -5}
    pools.create_assignment(PoolAssignment(one,1,.25,start_date='2026-04-01',end_date='2026-04-30'))
    later = authorized.query('SELECT eppm.dashboard_resource_breakdown(%s,%s)',([1,2],date(2026,1,1)))[0][0]
    assert next(pool for pool in later['pools'] if pool['pool_id'] == one)['available']['2026-Q2'] == .75
    for metric in ('allocation','overallocation'):
        assert sum(pool[metric]['2026-Q1'] for pool in report['pools']) == report[metric]['2026-Q1']
        consumers = authorized.query('SELECT eppm.dashboard_resource_breakdown(%s,%s,%s,%s,%s)',
            ([1,2],date(2026,1,1),'2026-Q1',one,metric))[0][0]['consumers']
        assert consumers == [1]
    unrelated = pools.create_pool(ResourcePool('Unrelated'))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query('SELECT eppm.dashboard_resource_breakdown(%s,%s,%s,%s)',([1],date(2026,1,1),'2026-Q1',unrelated))
