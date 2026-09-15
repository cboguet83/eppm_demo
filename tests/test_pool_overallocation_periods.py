"""Structured overload periods preserve gaps and changing excess capacity."""

from datetime import date

from app.domain.resources.models import DailyOverassignment, PoolCapacityDetail
from app.domain.resources.overallocation import overallocation_periods


def test_periods_split_on_gaps_and_excess_changes_and_keep_pools_separate():
    first = PoolCapacityDetail(1, 'Alpha', 2, 4, 0, True, 2,
        daily_overassignments=[
            DailyOverassignment('2027-01-05', 2, 3, 1),
            DailyOverassignment('2027-01-03', 2, 4, 2),
            DailyOverassignment('2027-01-02', 2, 3, 1),
            DailyOverassignment('2027-01-01', 2, 3, 1),
        ])
    second = PoolCapacityDetail(2, 'Beta', 2, 3, 0, True, 1,
        daily_overassignments=[DailyOverassignment('2027-01-06', 2, 3, 1)])
    result = overallocation_periods([second, first])
    assert [(row.pool_name, row.start_date.day, row.stop_date.day, row.fte)
            for row in result] == [
        ('Alpha', 1, 2, 1), ('Alpha', 3, 3, 2), ('Alpha', 5, 5, 1), ('Beta', 6, 6, 1),
    ]
    assert result[0].start_date == date(2027, 1, 1)
    assert overallocation_periods([]) == []
