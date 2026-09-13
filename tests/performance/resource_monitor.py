"""Sample Docker-reported utilization for explicitly selected benchmark containers."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import json
import math
from pathlib import Path
import re
import subprocess
from threading import Event, Thread
from time import monotonic, time


_UNITS = {'B': 1, 'kB': 1000, 'KB': 1000, 'MB': 1000**2, 'GB': 1000**3,
          'TB': 1000**4, 'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3, 'TiB': 1024**4}


def memory_bytes(value: str) -> int:
    """Convert Docker's formatted quantity, retaining its limited precision."""
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)', value.strip())
    if match is None or match[2] not in _UNITS:
        raise ValueError('Unknown Docker memory quantity.')
    return round(float(match[1]) * _UNITS[match[2]])


def decode_statistics(output: str, identities: Mapping[str, str]) -> dict[str, dict[str, float | int]]:
    """Accept only the requested identities and numeric resource fields."""
    services = {identity: service for service, identity in identities.items()}
    result = {}
    for line in output.splitlines():
        row = json.loads(line)
        service = services[row['ID']]
        if service in result:
            raise ValueError('Duplicate Docker statistics identity.')
        cpu = float(row['CPUPerc'].removesuffix('%'))
        if not math.isfinite(cpu) or cpu < 0:
            raise ValueError('Invalid Docker CPU percentage.')
        used, limit = row['MemUsage'].split('/')
        pids = int(row['PIDs'])
        if pids < 0:
            raise ValueError('Invalid Docker process count.')
        result[service] = {'cpu_percent': cpu, 'memory_bytes_approx': memory_bytes(used),
                           'memory_limit_bytes_approx': memory_bytes(limit), 'pids': pids}
    if result.keys() != identities.keys():
        raise ValueError('Incomplete Docker statistics sample.')
    return result


@contextmanager
def sample_containers(identities: Mapping[str, str], path: Path, *, interval: float = 2) -> Iterator[None]:
    """Observe owned container IDs; record failures without stopping browser workers.

    Docker output is decoded through an allowlist. Environment variables, command
    lines and subprocess error text are never retained. Shutdown waits for at most
    the current bounded subprocess, and does not stop or change any container.
    """
    selected = dict(identities)
    if (not selected or len(set(selected.values())) != len(selected)
            or any(re.fullmatch(r'[0-9a-f]{64}', identity) is None for identity in selected.values())
            or not math.isfinite(interval) or interval <= 0):
        raise ValueError('Require unique full container IDs and a positive sampling interval.')
    stop = Event()
    with path.open('w', encoding='utf-8', buffering=1) as target:
        def observe() -> None:
            while not stop.is_set():
                began = monotonic()
                entry = {'started_epoch': time()}
                try:
                    command = subprocess.run(
                        ['docker', 'stats', '--no-stream', '--no-trunc', '--format', 'json', *selected.values()],
                        capture_output=True, text=True, timeout=10, check=False,
                    )
                    if command.returncode:
                        entry.update(ok=False, error_type='DockerExit', exit_code=command.returncode)
                    else:
                        entry.update(ok=True, containers=decode_statistics(command.stdout, selected))
                except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as error:
                    entry.update(ok=False, error_type=type(error).__name__)
                entry.update(epoch=time(), collection_seconds=monotonic() - began)
                target.write(json.dumps(entry) + '\n')
                stop.wait(max(0, interval - (monotonic() - began)))

        worker = Thread(target=observe, name='benchmark-container-resources')
        worker.start()
        try:
            yield
        finally:
            stop.set()
            worker.join()
