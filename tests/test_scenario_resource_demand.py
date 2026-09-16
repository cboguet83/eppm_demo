"""Alternative allocations share active demand semantics and normalize CSV dates."""

import pytest

from app.domain.planning.plans import PlanContent
from app.domain.planning.schedule_template import parse_template
from app.domain.resources.models import PoolAssignment
from app.domain.resources.scenario_demand import scenario_pool_demand, comparison_pool_demand


@pytest.mark.parametrize('value,format,expected', [
    ('1/6/26', 'DD/MM/YYYY', '2026-06-01'),
    ('6/1/26', 'MM/DD/YYYY', '2026-06-01'),
    ('1/6/2026', 'DD/MM/YYYY', '2026-06-01'),
    ('1/6/99', 'DD/MM/YYYY', '2099-06-01'),
    ('29/2/24', 'DD/MM/YYYY', '2024-02-29'),
])
def test_short_csv_dates_resolve_explicit_order_and_twenty_first_century(value, format, expected):
    steps = parse_template(f'step_number,task_name,start_date,end_date\n1,Task,{value},{value}\n', date_format=format)
    assert steps[0].values['start_date'] == steps[0].values['end_date'] == expected


def test_invalid_short_date_is_still_rejected():
    with pytest.raises(ValueError, match='Invalid start_date'):
        parse_template('step_number,task_name,start_date,end_date\n1,Task,29/2/25,1/3/25\n', date_format='DD/MM/YYYY')


def test_unambiguous_month_first_date_sets_order_for_whole_csv():
    steps = parse_template('step_number,task_name,start_date,end_date\n'
                           '1,Task,9/20/2025,10/1/2026\n', date_format='DD/MM/YYYY')
    assert steps[0].values['start_date'] == '2025-09-20'
    assert steps[0].values['end_date'] == '2026-10-01'


def test_comparison_substitutes_only_displayed_projects_and_keeps_scopes():
    active = {1: [dict(project_id=pid, task_id=None, start_date='2027-01-01',
                       end_date='2027-01-01', fte_assigned=pid) for pid in range(1, 6)]}
    alternatives = {pid: PlanContent(tasks=[dict(id=pid, start_date='2027-01-01', end_date='2027-01-01')],
                                     assignments=[PoolAssignment(1, pid, pid * 10)]) for pid in [1, 3]}
    usage = comparison_pool_demand(active, alternatives, {1, 2, 3}, {1, 2, 3, 4})
    assert usage[1]['total'] == {'2027-01-01': 46}
    assert usage[1]['selected'] == {'2027-01-01': 42}
    # Excluded project statuses exclude both their active and alternative demand.
    usage = comparison_pool_demand(active, alternatives, {1, 2, 3}, {1, 2, 4})
    assert usage[1]['total'] == {'2027-01-01': 16}
    assert usage[1]['selected'] == {'2027-01-01': 12}
    alternatives[1] = PlanContent()
    usage = comparison_pool_demand(active, alternatives, {1}, {1})
    assert usage[1] == {'total': {}, 'selected': {}}


def test_scenario_demand_resolves_relative_dates_and_deduplicates_project_allocations():
    content = PlanContent(tasks=[dict(id=10, task_name='Task', start_date='2027-01-01', end_date='2027-01-05')],
        assignments=[PoolAssignment(1, 1, 1), PoolAssignment(1, 1, 2, task_id=10,
            schedule_anchor='end', offset_days=1, duration_days=2),
            PoolAssignment(2, 1, .5, task_id=10, start_date='2027-02-01', end_date='2027-02-01')])
    usage = scenario_pool_demand({1: content})
    assert usage[1] == {**{f'2027-01-0{day}': 1 for day in range(1, 6)}, '2027-01-06': 2, '2027-01-07': 2}
    assert usage[2] == {'2027-02-01': .5}
    assert scenario_pool_demand({}) == {}
