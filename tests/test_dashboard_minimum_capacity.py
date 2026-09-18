"""Dashboard periods use minimum capacity without changing daily peak excess."""

from datetime import date, timedelta

import pytest

from app.application.services.dashboard_resource_peaks import individual_pool_peaks
from app.domain.dashboard import quarterly_capacity
from app.domain.resources.models import PoolCapacityDetail


@pytest.mark.parametrize('calendar,expected', [
    ({'2027-06-01': 3}, 3), ({'2027-06-01': 0}, 0),
    ({'2027-06-01': 5}, 4), ({}, 4),
    ({(date(2027, 4, 1) + timedelta(days=i)).isoformat(): 5 for i in range(91)}, 5),
    ({'2027-03-31': 0, '2027-07-01': 0}, 4),
])
def test_period_minimum_respects_sparse_calendars_and_complete_coverage(calendar, expected):
    pools = [dict(pool_id=1, name='Team K', allocation={'2027-Q2': 0},
                  overallocation={'2027-Q2': 0}, available={'2027-Q2': 0})]
    result = individual_pool_peaks(pools, [], [[1, 4, calendar]], 2027)
    assert result[0]['capacity']['2027-Q2'] == expected
    detail = PoolCapacityDetail(1, 'Team K', 4, 0, 0, False, 0,
        effective_capacity_fte=4, daily_effective_capacity=calendar)
    assert quarterly_capacity([detail], 2027)['2027-Q2'] == expected


def test_team_k_peaks_keep_actual_day_capacity_while_displaying_quarter_minimum():
    pools = [dict(pool_id=1, name='Team K', allocation={'2027-Q2': 0},
                  overallocation={'2027-Q2': 0}, available={'2027-Q2': 0})]
    result = individual_pool_peaks(pools,
        [[1, '2027-05-17', 5.2, 4], [1, '2027-06-01', 5, 3]],
        [[1, 4, {'2027-06-01': 3}]], 2027)[0]
    assert result['capacity']['2027-Q2'] == 3
    assert result['allocation']['2027-Q2'] == 5.2
    assert result['overallocation']['2027-Q2'] == 2
