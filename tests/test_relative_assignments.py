"""Inclusive calendar offsets, moving owners, and invalid persisted modes."""

from dataclasses import replace
from datetime import date

import pytest

from app.domain.resources.capacity import resolve_assignments
from app.domain.resources.inputs import CapacityInputs
from app.domain.resources.models import PoolAssignment
from app.domain.resources.rules import normalize_assignment
from app.domain.resources.scheduling import relative_period


@pytest.mark.parametrize('anchor,offset,expected', [
    ('start', 10, ('2026-06-10', '2026-06-14')),
    ('end', 10, ('2026-07-10', '2026-07-14')),
    ('end', -10, ('2026-06-20', '2026-06-24')),
])
def test_anchor_offset_and_inclusive_duration(anchor, offset, expected):
    assert relative_period('2026-05-31', '2026-06-30', anchor, offset, 5) == expected


def test_capacity_dates_follow_task_and_project_moves():
    row = dict(id=1, project_id=1, task_id=2, task_name='Task', fte_assigned=1,
               task_start_date='2026-05-31', task_end_date='2026-06-30',
               schedule_anchor='start', offset_days=10, duration_days=5)
    inputs = CapacityInputs(1, assignments=[row])
    assert resolve_assignments(inputs, date(2026, 1, 1))[0]['start_date'] == '2026-06-10'
    row['task_start_date'] = '2026-06-30'
    resolved = resolve_assignments(inputs, date(2026, 1, 1))[0]
    assert (resolved['start_date'], resolved['end_date']) == ('2026-07-10', '2026-07-14')
    row.update(task_id=None, task_start_date=None, task_end_date=None, schedule_anchor='end')
    inputs.project_bounds = {1: ('2026-01-01', '2026-08-31')}
    assert resolve_assignments(inputs, date(2026, 1, 1))[0]['start_date'] == '2026-09-10'


@pytest.mark.parametrize('change', [
    dict(schedule_anchor='other'), dict(offset_days=None), dict(offset_days=True),
    dict(offset_days=1.5), dict(duration_days=0), dict(duration_days=9126),
    dict(start_date='2026-05-31'), dict(end_date='2026-06-30'),
])
def test_relative_mode_rejects_mixed_dates_and_invalid_parameters(change):
    assignment = PoolAssignment(1, 1, 1, schedule_anchor='start', offset_days=10, duration_days=5)
    with pytest.raises(ValueError):
        normalize_assignment(replace(assignment, **change))


def test_relative_mode_keeps_dates_absent():
    assignment = normalize_assignment(PoolAssignment(1, 1, 1, schedule_anchor='end', offset_days=10, duration_days=5))
    assert assignment.start_date is assignment.end_date is None
