"""Interval sweep must match the previous exact daily deduplication rules."""

from app.domain.resources.capacity_rules import accumulate_daily_usage

from collections import defaultdict
from datetime import date, timedelta
import random
import unittest

from app.domain.resources.timeline import demand_timeline


class CapacityTimelineTests(unittest.TestCase):
    def test_sweep_matches_daily_reference_for_random_overlapping_assignments(self):
        rng = random.Random(932)
        origin = date(2026, 1, 1)
        for _ in range(30):
            assignments = []
            project, tasks = defaultdict(dict), defaultdict(dict)
            for index in range(90):
                pid = rng.randint(1, 12)
                start = origin + timedelta(days=rng.randint(0, 25))
                end = start + timedelta(days=rng.randint(-1, 15))
                task = index if rng.random() < .7 else None
                fte = rng.choice([0, .1, .25, 1, 2.5])
                assignments.append(dict(project_id=pid, task_id=task, start_date=str(start), end_date=str(end), fte_assigned=fte))
                accumulate_daily_usage((project if task is None else tasks)[pid], str(start), str(end), fte)
            dates = set().union(*(list(project.values()) + list(tasks.values())))
            expected = {day: round(sum(max(project[p].get(day,0),tasks[p].get(day,0)) for p in range(1,13)),3) for day in dates}
            self.assertEqual(demand_timeline(assignments), expected)
            self.assertEqual(demand_timeline(assignments, [1]), demand_timeline([a for a in assignments if a['project_id']==1]))

    def test_zero_dates_gaps_invalid_dates_and_safety_cap(self):
        def assignment(start, end, value):
            return dict(project_id=1, task_id=None, start_date=start, end_date=end, fte_assigned=value)
        result = demand_timeline([assignment('2026-01-01','2026-01-02',0), assignment('2026-01-04','2026-01-04',1), assignment('invalid','2026-02-01',9)])
        self.assertEqual(result, {'2026-01-01':0, '2026-01-02':0, '2026-01-04':1})
        self.assertEqual(len(demand_timeline([assignment('2000-01-01','2100-01-01',1)])), 365*25)
