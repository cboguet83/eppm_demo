"""Inclusive resource assignment scoping and status-selected demand totals."""

import pytest

from app.domain.resources.allocation_scope import scoped_assignments, scope_pool_detail
from app.domain.resources.models import PoolCapacityDetail


def assignment(identity, project, start, end, fte, task=None):
    return dict(id=identity, project_id=project, project_name=str(project), task_id=task,
                task_name='Task', start_date=start, end_date=end, fte_assigned=fte,
                notes='', is_custom_period=True)


def test_q3_popup_scope_includes_boundaries_and_excludes_other_projects_and_periods():
    rows = [assignment(1, 1, '2025-06-01', '2025-07-01', 1),
            assignment(2, 1, '2025-09-30', '2025-10-02', 1),
            assignment(3, 2, '2025-08-01', '2025-08-31', 2),
            assignment(4, 1, '2025-10-01', '2025-10-31', 3),
            assignment(5, 1, '2025-07-01', '2025-09-30', 0)]
    assert [r['id'] for r in scoped_assignments(rows, {1}, '2025-07-01', '2025-09-30')] == [1, 2]
    assert [r['id'] for r in scoped_assignments(rows, {1, 2}, '2025-07-01', '2025-09-30')] == [1, 2, 3]
    assert scoped_assignments(rows, set()) == []
    with pytest.raises(ValueError):
        scoped_assignments(rows, None, '2025-10-01', '2025-09-30')


def test_status_project_scope_recalculates_total_demand_and_preserves_capacity():
    rows = [assignment(1, 1, '2025-07-01', '2025-07-02', 2),
            assignment(2, 1, '2025-07-01', '2025-07-02', 1, task=7),
            assignment(3, 2, '2025-07-01', '2025-07-02', 10)]
    detail = PoolCapacityDetail(pool_id=1, pool_name='Pool A', total_capacity_fte=5,
                               effective_capacity_fte=5, assignments=rows,
                               daily_effective_capacity={'2025-07-02': 1}, peak_assigned_fte=12,
                               total_assigned_fte_scalar=12, is_overassigned=True, peak_excess_fte=11)
    active = scope_pool_detail(detail, {1})
    assert active.daily_usage == {'2025-07-01': 2, '2025-07-02': 2}
    assert active.peak_excess_fte == 1
    assert active.total_assigned_fte_scalar == 2
    assert active.capacity_calendar == detail.capacity_calendar
    assert len(detail.assignments) == 3
    empty = scope_pool_detail(detail, set())
    assert empty.daily_usage == {} and not empty.is_overassigned
