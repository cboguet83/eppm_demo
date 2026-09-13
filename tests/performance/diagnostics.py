"""Summarize observed diagnostic windows without inventing unmeasured time."""

from collections.abc import Mapping
import json
from pathlib import Path
from statistics import mean


def read_samples(path: Path) -> list[dict]:
    """Read completed JSON lines; tolerate only an unfinished final append."""
    if not path.exists():
        return []
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    result = []
    for index, line in enumerate(lines):
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            if index != len(lines) - 1 or line.endswith('\n'):
                raise
    return result


def counter_changes(before: Mapping[str, float], after: Mapping[str, float]) -> dict[str, float] | None:
    """Reject reset/disappearing counters instead of reporting negative work."""
    if before.keys() - after.keys():
        return None
    differences = {name: value - before.get(name, 0) for name, value in after.items()}
    return differences if all(value >= 0 for value in differences.values()) else None


def _window(rows: list[dict], start: float, end: float) -> list[dict]:
    return sorted((row for row in rows if start <= row['epoch'] <= end), key=lambda row: row['epoch'])


def _coverage(rows: list[dict]) -> dict:
    return {'samples': len(rows), 'first_epoch': rows[0]['epoch'] if rows else None,
            'last_epoch': rows[-1]['epoch'] if rows else None,
            'observed_seconds': rows[-1]['epoch'] - rows[0]['epoch'] if len(rows) >= 2 else 0}


def runtime_summary(rows: list[dict], start: float, end: float) -> dict:
    """Difference cumulative boundaries strictly inside the requested phase."""
    selected = _window(rows, start, end)
    result = _coverage(selected)
    if len(selected) < 2:
        return result | {'status': 'insufficient_samples'}
    first, last = selected[0], selected[-1]
    metrics = {}
    for name, final in last['cumulative'].items():
        initial = first['cumulative'].get(name, {})
        metrics[name] = counter_changes({key: initial.get(key, 0) for key in ('count', 'seconds')},
                                        {key: final[key] for key in ('count', 'seconds')})
    disappeared = first['cumulative'].keys() - last['cumulative'].keys()
    result.update(status='counter_reset' if disappeared or None in metrics.values() else 'observed', metrics=metrics)
    before, after = first.get('pools', []), last.get('pools', [])
    # The application owns one pool; an unexpected pool count is not a comparable counter series.
    if len(before) == len(after) == 1:
        gauges = {'pool_min', 'pool_max', 'pool_size', 'pool_available', 'requests_waiting'}
        result['pool_counters'] = counter_changes({k: v for k, v in before[0].items() if k not in gauges},
                                                   {k: v for k, v in after[0].items() if k not in gauges})
        result['maximum_waiting_requests'] = max(row['pools'][0].get('requests_waiting', 0)
                                                 for row in selected if len(row.get('pools', [])) == 1)
    return result


def postgres_summary(rows: list[dict], start: float, end: float) -> dict:
    """Report database counters and sampled active-backend wait occupancy."""
    selected = _window(rows, start, end)
    result = _coverage(selected)
    if len(selected) < 2:
        return result | {'status': 'insufficient_samples'}
    changes = counter_changes(selected[0]['cumulative'], selected[-1]['cumulative'])
    waits = {}
    for previous, current in zip(selected, selected[1:]):
        interval = current['epoch'] - previous['epoch']
        for category, count in previous['active_wait_categories'].items():
            waits[category] = waits.get(category, 0) + count * interval
    return result | {'status': 'observed' if changes is not None else 'counter_reset', 'counters': changes,
                     'sampled_active_backend_seconds_by_wait_category': waits}


def container_summary(rows: list[dict], start: float, end: float) -> dict:
    """Keep missing and failed observations distinct from zero utilization."""
    selected = _window(rows, start, end)
    groups = {}
    for row in selected:
        if row['ok']:
            for name, values in row['containers'].items():
                groups.setdefault(name, []).append(values)
    services = {name: {'samples': len(values), 'mean_cpu_percent': mean(v['cpu_percent'] for v in values),
                       'max_cpu_percent': max(v['cpu_percent'] for v in values),
                       'max_memory_bytes_approx': max(v['memory_bytes_approx'] for v in values),
                       'max_pids': max(v['pids'] for v in values)} for name, values in groups.items()}
    return _coverage(selected) | {'failed_samples': sum(not row['ok'] for row in selected), 'containers': services}


def summarize_phases(directory: Path, phases: list[dict]) -> list[dict]:
    """Attach separate server, database and container evidence to every phase."""
    runtime = read_samples(directory / 'data/runtime-timings.jsonl')
    postgres = read_samples(directory / 'data/postgresql-timings.jsonl')
    containers = read_samples(directory / 'container-timings.jsonl')
    return [phase | {'runtime': runtime_summary(runtime, phase['started_epoch'], phase['ended_epoch']),
                     'postgresql': postgres_summary(postgres, phase['started_epoch'], phase['ended_epoch']),
                     'containers': container_summary(containers, phase['started_epoch'], phase['ended_epoch'])}
            for phase in phases]
