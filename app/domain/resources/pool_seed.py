"""Deterministic Ressort A layout and whole-period allocation slots in milli-FTE."""

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


class _CapacityLedger:
    """Track concurrent milli-FTE using inclusive task boundaries, without daily rows."""

    def __init__(self) -> None:
        self.events: dict[str, dict[int, int]] = {}

    def remaining(self, pool_name: str, start: date, end: date, limit: int) -> int:
        """Return the smallest spare capacity over the complete requested interval."""
        if end < start:
            raise ValueError('Assignment ends before it starts.')
        first, last = start.toordinal(), end.toordinal()
        active = peak = 0
        for day, delta in sorted(self.events.get(pool_name, {}).items()):
            if day > last:
                break
            if day > first:
                peak = max(peak, active)
            active += delta
            if day >= first:
                peak = max(peak, active)
        return max(0, limit - max(peak, active))

    def reserve(self, row: SeedDemand, sign: int = 1) -> None:
        """Reserve or release a whole interval, including date.max safely."""
        events = self.events.setdefault(row.pool_name, {})
        for boundary, delta in ((row.start.toordinal(), row.milli_fte),
                                (row.end.toordinal() + 1, -row.milli_fte)):
            events[boundary] = events.get(boundary, 0) + sign * delta
            if not events[boundary]:
                del events[boundary]


def _utilization_rates(seed: int) -> tuple[list[SeedPool], dict[str, int]]:
    """Retain seven overallocated pools, four underallocated pools and E1/E2 limits."""
    pools = list(POOLS)
    random.Random(seed).shuffle(pools)
    ordinary = [pool for pool in pools if pool.name not in {'pool E1', 'pool E2'}]
    rates = {pool.name: 150 if index < 7 else 75 if index < 11 else 100
             for index, pool in enumerate(ordinary)}
    rates.update({'pool E1': 80, 'pool E2': 80})
    return pools, rates


def plan_demand(projects: list[ProjectPeriod], seed: int, *,
                tasks: list[TaskPeriod] | None = None) -> tuple[tuple[SeedDemand, ...], dict[str, int], int]:
    """Allocate whole periods in project-ID order without monthly custom dates.

    The first quarter of projects (rounded up) uses project-level slots capped at
    half each pool's configured demand. Remaining projects use the other half on
    tasks. A project whose complete set of task slots cannot fit stays unallocated.
    Each slot is 0.1 to 5 FTE. Pool demand categories are preserved; allocations
    never exceed their configured category limit, including E1/E2 at 80%.
    """
    ordered = sorted(projects, key=lambda project: project.project_id)
    eligible: dict[int, list[TaskPeriod]] = {}
    for task in sorted(tasks or [], key=lambda task: (task.project_id, task.task_id)):
        if task.end < task.start:
            raise ValueError('Task ends before it starts.')
        eligible.setdefault(task.project_id, []).append(task)
    pools, rates = _utilization_rates(seed)
    rng = random.Random(seed)
    ledgers = (_CapacityLedger(), _CapacityLedger())
    cursors = [0, 0]
    rows: list[SeedDemand] = []
    cutoff = (len(ordered) + 3) // 4
    for index, project in enumerate(ordered):
        if project.end < project.start:
            raise ValueError('Project ends before it starts.')
        if not eligible.get(project.project_id):
            continue
        phase = int(index >= cutoff)
        targets = eligible[project.project_id] if phase else [project]
        staged: list[SeedDemand] = []
        original_cursor = cursors[phase]
        for target in targets:
            placed = False
            for offset in range(len(pools)):
                pool_index = (cursors[phase] + offset) % len(pools)
                pool = pools[pool_index]
                ceiling = 180 if rates[pool.name] > 100 else rates[pool.name]
                limit = pool.capacity * 1000 * ceiling // 200
                spare = ledgers[phase].remaining(pool.name, target.start, target.end, limit)
                maximum = min(5000, spare) // 100
                if maximum < 1:
                    continue
                row = SeedDemand(pool.name, project.project_id, target.start, target.end,
                                 rng.randint(1, maximum) * 100,
                                 target.task_id if isinstance(target, TaskPeriod) else None)
                ledgers[phase].reserve(row)
                staged.append(row)
                cursors[phase] = (pool_index + 1) % len(pools)
                placed = True
                break
            if not placed:
                for row in staged:
                    ledgers[phase].reserve(row, -1)
                staged = []
                cursors[phase] = original_cursor
                break
        rows.extend(staged)
    used = {row.pool_name for row in rows}
    omitted = len(ordered) - len({row.project_id for row in rows})
    return tuple(rows), {name: rate for name, rate in rates.items() if name in used}, omitted
