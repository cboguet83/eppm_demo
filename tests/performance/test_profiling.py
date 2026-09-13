"""Concurrent diagnostic sampling must not interrupt workers or retain values."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier, Event

from tests.performance.profiling import StackProfiler


def test_sampling_observes_concurrent_workers_without_retaining_arguments(tmp_path: Path) -> None:
    ready, release = Barrier(3), Event()
    private_value = "argument-must-not-appear-in-diagnostics"

    def worker(value: str) -> str:
        ready.wait(timeout=5)
        assert release.wait(timeout=5)
        return value

    profiler = StackProfiler(tmp_path / 'stacks.json', source_prefix=__file__)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, private_value) for _ in range(2)]
        ready.wait(timeout=5)
        try:
            profiler.sample()
            profiler.write()
        finally:
            release.set()
        assert [future.result() for future in futures] == [private_value, private_value]
    serialized = profiler.path.read_text(encoding='utf-8')
    result = json.loads(serialized)
    assert private_value not in serialized
    assert sum(stack['count'] for stack in result['stacks']) == 2
    assert all(any(location['function'] == 'worker' for location in stack['locations'])
               for stack in result['stacks'])


def test_stack_limit_reports_dropped_observations(tmp_path: Path) -> None:
    ready, release = Event(), Event()

    def worker() -> None:
        ready.set()
        assert release.wait(timeout=5)

    profiler = StackProfiler(tmp_path / 'stacks.json', source_prefix=__file__, max_stacks=0)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(worker)
        assert ready.wait(timeout=5)
        try:
            profiler.sample()
        finally:
            release.set()
        future.result()
    assert profiler.stacks == {}
    assert profiler.dropped == 1


def test_sampler_shutdown_writes_final_counts(tmp_path: Path) -> None:
    profiler = StackProfiler(tmp_path / 'stacks.json')
    profiler.start()
    profiler.stop()
    assert json.loads(profiler.path.read_text(encoding='utf-8'))['kind'] == 'thread_stack_samples'
