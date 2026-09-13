"""Pure generation of the accepted demo schedules and cross-project dependencies."""

from dataclasses import dataclass
from datetime import date, timedelta
import random


PHASES = (('FAI', 'Phase 1 - FAI', 365), ('APS', 'Phase 2 - APS', 365),
          ('APD1', 'Phase 3 - APD1', 365), ('APD2', 'Phase 4 - APD2', 548),
          ('EXE', 'Phase 5 - EXE', 182), ('CHA', 'Phase 6 - CHA', 730), ('DEF', 'Phase 7 - DEF', 548))
MILESTONES = (('AUT', 'Autorisation 1'), ('VAL', 'Validation'), ('QUAL', 'Controle Qualité'), ('CER', 'Certificat Conformité'))
type TaskRow = tuple[int, str, str, date, date, int, str]
type DependencyRow = tuple[int, int | None, int | None, str, int]


@dataclass(frozen=True)
class _Item:
    code: str
    name: str
    phase: str
    start: date
    end: date
    milestone: bool = False


def _single_phase(minimum: int, maximum: int, rng: random.Random) -> bool:
    """Keep schedule shape and its random draw independent of project templates."""
    single = minimum <= 1 <= maximum
    multiple = maximum >= 2 or minimum == 0 and maximum >= 1
    if single and not multiple:
        return True
    if multiple and not single:
        return False
    return rng.random() < 0.20


def _items(start: date, minimum: int, maximum: int, rng: random.Random) -> list[_Item]:
    """Build phases, anchored milestones and any required extra work packages."""
    phases = PHASES[:maximum]
    high = min(len(MILESTONES), max(0, maximum - len(phases)))
    low = min(high, max(0, minimum - len(phases)))
    count = rng.randint(low, high) if high > 0 else 0
    milestones = rng.sample(MILESTONES, count) if count else []
    ends: dict[str, date] = {}
    result = []
    current = start
    for code, phase, duration in phases:
        end = current + timedelta(days=duration)
        ends[code] = end
        result.append(_Item(code, code, phase, current, end))
        current = end
    anchors = {'AUT': ends.get('APS', ends.get('APD1', current)), 'VAL': ends.get('APD2', current),
               'QUAL': ends.get('CHA', current), 'CER': ends.get('DEF', current)}
    for code, name in milestones:
        day = anchors[code]
        result.append(_Item(code, code, name, day, day, True))
    package = 1
    while len(result) < minimum:
        end = current + timedelta(days=30)
        result.append(_Item(f'WP{package}', f'Work package {package}', 'EXE', current, end))
        current = end
        package += 1
    return sorted(result, key=lambda item: (item.start, item.milestone))


def _progress(status: str, index: int, active: int, milestone: bool, rng: random.Random) -> int:
    """Apply the established progress distribution without changing random order."""
    if status == 'Completed':
        return 100
    if status == 'Draft':
        return 0
    if status != 'In Progress':
        return rng.choice((0, 0, 25, 50, 75, 100))
    if index < active:
        return 100
    if index == active:
        return 100 if milestone else rng.choice((25, 50, 75))
    return 0


def generate_schedules(projects: list[tuple[int, str]], minimum: int, maximum: int,
                       rng: random.Random) -> tuple[list[TaskRow], list[DependencyRow]]:
    """Generate task rows with one-based logical IDs for later native allocation.

    The caller supplies the same random stream used for project generation.
    Logical dependency IDs are replaced with reserved PostgreSQL IDs at insertion.
    """
    tasks: list[TaskRow] = []
    by_project: dict[int, list[int]] = {identity: [] for identity, _ in projects}
    codes: dict[int, dict[str, int]] = {identity: {} for identity, _ in projects}
    for project, status in projects:
        start = date(2025, 6, 1) + timedelta(days=rng.randint(0, 365))
        if maximum == 0:
            continue
        if _single_phase(minimum, maximum, rng):
            end = start + timedelta(days=rng.randint(90, 1095))
            progress = 100 if status == 'Completed' else 0 if status == 'Draft' else rng.choice((0, 25, 50, 75, 100))
            tasks.append((project, 'N/A', 'Phase 0 - N/A', start, end, progress, 'Phase unique N/A'))
            by_project[project].append(len(tasks))
            codes[project]['N/A'] = len(tasks)
            continue
        items = _items(start, minimum, maximum, rng)
        active = rng.randint(0, len(items) - 1)
        for index, item in enumerate(items):
            progress = _progress(status, index, active, item.milestone, rng)
            tasks.append((project, item.name, item.phase, item.start, item.end, progress, f'Livrable {item.name} ({item.phase})'))
            by_project[project].append(len(tasks))
            codes[project][item.code] = len(tasks)
    return tasks, _dependencies([identity for identity, _ in projects], by_project, codes, rng)


def _dependencies(projects: list[int], tasks: dict[int, list[int]], codes: dict[int, dict[str, int]],
                   rng: random.Random) -> list[DependencyRow]:
    """Retain phase/milestone links and the earlier-project-only termination rule."""
    result: list[DependencyRow] = []
    phases = [row[0] for row in PHASES]
    pairs = [*zip(phases, phases[1:]), ('APS', 'AUT'), ('APD2', 'VAL'), ('CHA', 'QUAL'), ('DEF', 'CER')]
    for index, project in enumerate(projects):
        if not tasks[project]:
            continue
        mapping = codes[project]
        result.extend((mapping[current], mapping[previous], None, 'FS', 0)
                      for previous, current in pairs if previous in mapping and current in mapping)
        if index == 0 or rng.random() >= 0.22:
            continue
        source = projects[rng.randint(0, index - 1)]
        if rng.random() < 0.40 or not tasks[source]:
            result.append((tasks[project][0], None, source, rng.choice(('FS', 'SS')), rng.choice((0, 2, 5))))
        else:
            predecessor = rng.choice(tasks[source])
            result.append((tasks[project][0], predecessor, source, rng.choice(('FS', 'SS', 'FF')), rng.choice((0, 1, 3))))
    return result
