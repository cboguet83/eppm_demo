"""Deterministic Ressort A layout and aggregate project demand in milli-FTE."""

from dataclasses import dataclass
from datetime import date
import random


@dataclass(frozen=True)
class SeedPool:
    """Configured capacity and organizational parent of a seed pool."""

    name: str
    parent: str
    hierarchy_type: str
    capacity: int


GROUPS = (
    ('Ressort A', None, 'ressort'),
    *((f'Service {code}', 'Ressort A', 'service') for code in 'EGIMP'),
    ('Projets', 'Service P', 'division'),
)
POOLS = (
    SeedPool('pool BIM', 'Service P', 'division', 10),
    SeedPool('pool Tech', 'Service P', 'division', 10),
    *(SeedPool(f'team {code}', 'Projets', 'equipe', 4) for code in 'ABCDEFGHJK'),
    *(SeedPool(f'pool I{i}', 'Service I', 'division', capacity)
      for i, capacity in enumerate((3, 5, 8, 12, 16, 20), 1)),
    *(SeedPool(f'pool {code}{i}', f'Service {code}', 'division', capacity)
      for code in 'EGM' for i, capacity in enumerate((5, 6, 7, 8, 10), 1)),
)


@dataclass(frozen=True)
class ProjectPeriod:
    """Inclusive project demand dates, independent of persistence."""

    project_id: int
    start: date
    end: date


@dataclass(frozen=True)
class SeedDemand:
    """A positive share of a pool's combined demand on an inclusive interval."""

    pool_name: str
    project_id: int
    start: date
    end: date
    milli_fte: int
    task_id: int | None = None


@dataclass(frozen=True)
class TaskPeriod:
    """A dated task eligible for the task-level demonstration pools."""

    task_id: int
    project_id: int
    start: date
    end: date


TASK_POOLS = frozenset({'team C', 'team D', 'team E'})


def membership_intervals(projects: list[ProjectPeriod]) -> list[tuple[int, int, tuple[int, ...]]]:
    """Sweep inclusive dates into maximal constant-membership active intervals."""
    events: dict[int, list[tuple[int, bool]]] = {}
    for project in projects:
        if project.end < project.start:
            raise ValueError('Project demand ends before it starts.')
        events.setdefault(project.start.toordinal(), []).append((project.project_id, True))
        events.setdefault(project.end.toordinal() + 1, []).append((project.project_id, False))
    active: set[int] = set()
    result = []
    boundaries = sorted(events)
    for start, stop in zip(boundaries, boundaries[1:]):
        for identity, entering in events[start]:
            if entering:
                active.add(identity)
            else:
                active.remove(identity)
        if active:
            result.append((start, stop - 1, tuple(sorted(active))))
    return result


def monthly_utilization(pool_name: str, rate: int, day: date) -> int:
    """Vary monthly demand with bounded seasonal peaks and stable pool phases."""
    if rate > 200:
        raise ValueError('Combined demand exceeds 200% of pool capacity.')
    phase = sum(map(ord, pool_name)) % 3
    month = (day.month - 1 + phase) % 12
    if pool_name in {'pool E1', 'pool E2'}:
        rate = 80
    if rate > 100:
        return (85, 100, 115, 130, 160, 180, 145, 105, 95, 120, 150, 110)[month]
    return rate * (60, 70, 80, 90, 100, 80, 70, 90, 60, 80, 100, 70)[month] // 100


def _month_boundaries(first: int, last: int) -> list[int]:
    """Return first-of-month split points without overflowing date.max."""
    day = date.fromordinal(first)
    year, month = day.year, day.month
    result = []
    while (year, month) < (9999, 12):
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        boundary = date(year, month, 1).toordinal()
        if boundary > last:
            break
        result.append(boundary)
    return result


def _pool_demand(pool: SeedPool, projects: list[ProjectPeriod], rate: int) -> list[SeedDemand]:
    intervals = membership_intervals(projects)
    if not intervals:
        return []
    result = []
    for start, end, members in intervals:
        boundaries = [start, *_month_boundaries(start, end), end + 1]
        for first, stop in zip(boundaries, boundaries[1:]):
            percent = monthly_utilization(pool.name, rate, date.fromordinal(first))
            total = pool.capacity * 1000 * percent // 100
            share, remainder = divmod(total, len(members))
            if share < 1:
                raise ValueError('Allocation precision cannot give every active project a positive milli-FTE share.')
            if total > pool.capacity * 2000:
                raise ValueError('Combined demand exceeds 200% of pool capacity.')
            result.extend(SeedDemand(pool.name, identity, date.fromordinal(first), date.fromordinal(stop - 1),
                                     share + (index < remainder)) for index, identity in enumerate(members))
    return result


def plan_demand(projects: list[ProjectPeriod], seed: int, *,
                tasks: list[TaskPeriod] | None = None) -> tuple[tuple[SeedDemand, ...], dict[str, int], int]:
    """Allocate 90% of projects with seasonal pool demand and bounded E1/E2 usage.

    For fewer than 33 allocated projects, projects serve multiple pools so every
    pool is exercised. Empty catalogs have no demand or utilization categories.
    Ten percent unallocated uses nearest-whole rounding with halves rounded up.
    """
    rng = random.Random(seed)
    ordered = sorted(projects, key=lambda project: project.project_id)
    rng.shuffle(ordered)
    omitted = (len(ordered) + 5) // 10
    selected = ordered[omitted:]
    pool_order = list(POOLS)
    rng.shuffle(pool_order)
    rates = {pool.name: 150 if index < 7 else 75 if index < 11 else 100
             for index, pool in enumerate(pool_order)}
    rates.update({'pool E1': 80, 'pool E2': 80})
    assigned: dict[str, list[ProjectPeriod]] = {pool.name: [] for pool in POOLS}
    for index, project in enumerate(selected):
        assigned[pool_order[index % len(POOLS)].name].append(project)
    if selected:
        for index, pool in enumerate(pool_order):
            if not assigned[pool.name]:
                assigned[pool.name].append(selected[index % len(selected)])
    if tasks is not None:
        selected_ids = {project.project_id for project in selected}
        eligible = sorted((task for task in tasks if task.project_id in selected_ids), key=lambda task: task.task_id)
        task_projects = {task.project_id for task in eligible}
        for name in sorted(TASK_POOLS):
            undated = [project for project in assigned[name] if project.project_id not in task_projects]
            existing = {project.project_id for project in assigned['team B']}
            assigned['team B'].extend(project for project in undated if project.project_id not in existing)
            assigned[name] = [project for project in assigned[name] if project.project_id in task_projects]
            if not assigned[name] and eligible:
                fallback = eligible[0].project_id
                assigned[name] = [project for project in selected if project.project_id == fallback]
        rows = []
        for pool in POOLS:
            if pool.name not in TASK_POOLS:
                rows.extend(_pool_demand(pool, assigned[pool.name], rates[pool.name]))
                continue
            owners = {project.project_id for project in assigned[pool.name]}
            pool_tasks = {task.task_id: task for task in eligible if task.project_id in owners}
            periods = [ProjectPeriod(task.task_id, task.start, task.end) for task in pool_tasks.values()]
            for row in _pool_demand(pool, periods, rates[pool.name]):
                task = pool_tasks[row.project_id]
                rows.append(SeedDemand(row.pool_name, task.project_id, row.start, row.end, row.milli_fte, task.task_id))
        return tuple(rows), {name: rate for name, rate in rates.items() if any(row.pool_name == name for row in rows)}, omitted
    rows = tuple(row for pool in POOLS for row in _pool_demand(pool, assigned[pool.name], rates[pool.name]))
    return rows, rates if selected else {}, omitted
