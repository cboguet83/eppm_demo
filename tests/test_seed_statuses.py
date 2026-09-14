"""Exact capped project mixes and completed schedule cutoffs."""

from collections import Counter
from datetime import date
import random

import pytest

from app.domain.projects.seed_statuses import project_statuses
from app.infrastructure.postgresql.seed_schedules import generate_schedules


@pytest.mark.parametrize('count', [0, 1, 5, 19, 100, 1000])
def test_project_status_quotas_never_exceed_caps(count):
    statuses = project_statuses(count, random.Random(42))
    totals = Counter(statuses)
    assert len(statuses) == count
    for status, percent in [('Cancelled', 5), ('Completed', 10), ('Draft', 4), ('On Hold', 3)]:
        assert totals[status] == count * percent // 100
    assert totals['In Progress'] == count - sum(count * percent // 100 for percent in (5, 10, 4, 3))
    assert statuses == project_statuses(count, random.Random(42))


@pytest.mark.parametrize('minimum,maximum', [(0, 0), (1, 1), (7, 11), (50, 50)])
def test_completed_tasks_end_before_today_without_changing_durations_or_dependencies(minimum, maximum):
    projects = [(1, 'Completed'), (2, 'In Progress')]
    first, edges = generate_schedules(projects, minimum, maximum, random.Random(4), today=date(2026, 9, 14))
    later, later_edges = generate_schedules(projects, minimum, maximum, random.Random(4), today=date(2027, 9, 14))
    assert edges == later_edges
    for task, other in zip(first, later):
        assert task[4] >= task[3]
        assert task[4] - task[3] == other[4] - other[3]
        if task[0] == 1:
            assert task[4] < date(2026, 9, 14)
            assert other[4] < date(2027, 9, 14)
            assert task[5] == 100
        else:
            assert task == other
