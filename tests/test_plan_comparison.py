"""Plan comparison resolves identities, dates and capacity independently per side."""

from datetime import date
from dataclasses import replace
import pytest

from app.domain.planning.plans import PlanContent, compare_tasks, normalize_content
from app.domain.planning.plan_comparison import dependency_warnings, scenario_capacity
from app.domain.resources.models import PoolAssignment, PoolCapacityDetail


def task(identity, name, start='2027-01-01', end='2027-01-03'):
    return dict(id=identity, task_name=name, phase='General', description='', start_date=start, end_date=end)


def test_task_comparison_pairs_renames_and_retains_added_removed_tasks():
    result = compare_tasks(PlanContent(tasks=[task(1, 'Before'), task(2, 'Removed')]),
                           PlanContent(tasks=[task(1, 'Renamed'), task(3, 'Added')]))
    assert {row['id']: row['change'] for row in result} == {1: 'changed', 2: 'removed', 3: 'added'}


def test_scenario_demand_uses_same_capacity_and_resolves_relative_dates_per_side():
    reference = PlanContent(tasks=[task(1, 'Task')], assignments=[PoolAssignment(1, 1, 2, task_id=1,
        schedule_anchor='start', offset_days=0, duration_days=2)])
    alternative = replace(reference, tasks=[task(1, 'Task', '2027-01-05', '2027-01-07')])
    base = PoolCapacityDetail(1, 'Pool', 5, 0, 0, False, 0, effective_capacity_fte=3,
                              daily_effective_capacity={'2027-01-05': 1})
    before = scenario_capacity([base], {1: reference}, {1: 'Project'}, date(2027, 1, 1))[0]
    after = scenario_capacity([base], {1: alternative}, {1: 'Project'}, date(2027, 1, 1))[0]
    assert before.daily_usage == {'2027-01-01': 2, '2027-01-02': 2}
    assert not before.is_overassigned
    assert after.daily_usage == {'2027-01-05': 2, '2027-01-06': 2}
    assert after.peak_excess_fte == 1
    assert base.assignments == []


def test_dependency_comparison_reports_missing_and_changed_predecessors_without_cycles():
    dependent = PlanContent(tasks=[task(1, 'Dependent')], dependencies=[dict(task_id=1,
        predecessor_task_id=2, predecessor_project_id=None, link_type='FS', lag_days=0)])
    assert 'unavailable' in dependency_warnings({1: dependent})[1][0]
    predecessor = PlanContent(tasks=[task(2, 'Predecessor')])
    assert 'not satisfied' in dependency_warnings({1: dependent, 2: predecessor})[1][0]


@pytest.mark.parametrize('start,end', [('bad', None), ('2027-03-01', '2027-01-01')])
def test_plan_rejects_invalid_assignment_dates_before_persistence(start, end):
    content = PlanContent(assignments=[PoolAssignment(1, 1, 1, start_date=start, end_date=end)])
    with pytest.raises(ValueError, match='[Aa]ssignment'):
        normalize_content(1, content)


def test_temporary_task_ids_are_scoped_to_their_project_in_warnings():
    first = PlanContent(tasks=[task(-1, 'First', '2027-01-01', '2027-01-02'),
                               task(-2, 'Second', '2027-01-03', '2027-01-04')],
        dependencies=[dict(task_id=-2, predecessor_task_id=-1, predecessor_project_id=None, link_type='FS', lag_days=0)])
    other = PlanContent(tasks=[task(-1, 'Unrelated', '2027-12-01', '2027-12-02')])
    assert dependency_warnings({1: first, 2: other})[1] == []
