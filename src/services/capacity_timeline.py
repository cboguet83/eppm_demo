"""Exact pool demand using interval boundaries, not assignments × calendar days."""

from collections import defaultdict
from datetime import date


def demand_timeline(assignments, project_ids=None):
    """Sum max(project demand, task demand) per project on each occupied day.

    Work scales with assignment boundaries plus output days. Zero-demand dates,
    inclusive end dates and the existing 25-year safety cap are preserved.
    """
    wanted = None if project_ids is None else {int(p) for p in project_ids}
    projects = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    coverage = defaultdict(int)
    for assignment in assignments:
        pid = int(assignment['project_id'])
        if wanted is not None and pid not in wanted:
            continue
        try:
            start = date.fromisoformat(assignment['start_date'].strip()[:10]).toordinal()
            end = date.fromisoformat(assignment['end_date'].strip()[:10]).toordinal()
        except (ValueError, TypeError, AttributeError):
            continue
        stop = min(max(start, end) + 1, start + 365 * 25)
        kind = int(assignment.get('task_id') is not None)
        fte = float(assignment['fte_assigned'])
        projects[pid][start][kind] += fte
        projects[pid][stop][kind] -= fte
        coverage[start] += 1
        coverage[stop] -= 1
    changes = defaultdict(float)
    for events in projects.values():
        project = task = previous = 0.0
        for day in sorted(events):
            project += events[day][0]
            task += events[day][1]
            current = max(project, task)
            changes[day] += current - previous
            previous = current
    days = sorted(coverage)
    result = {}
    value = 0.0
    active = 0
    for index, day in enumerate(days[:-1]):
        value += changes[day]
        active += coverage[day]
        if active:
            rounded = round(value, 3)
            for ordinal in range(day, days[index + 1]):
                result[date.fromordinal(ordinal).isoformat()] = rounded
    return result
