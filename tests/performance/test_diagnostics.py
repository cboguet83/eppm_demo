"""Measurement windows must not absorb warmup work or conceal missing evidence."""

import json
from pathlib import Path
import subprocess
from threading import Event

import pytest

from tests.performance.diagnostics import (
    container_summary, counter_changes, postgres_summary, read_samples, runtime_summary,
)
from tests.performance.resource_monitor import decode_statistics, memory_bytes, sample_containers


def test_measurement_counter_window_excludes_warmup_and_cooldown() -> None:
    rows = [{'epoch': epoch, 'cumulative': {'db': {'count': count, 'seconds': count / 10,
                                                   'max_seconds': 50}},
             'pools': [{'requests_num': count, 'pool_size': 5, 'requests_waiting': 2}]}
            for epoch, count in ((9, 1000), (11, 1010), (19, 1020), (21, 2000))]
    result = runtime_summary(rows, 10, 20)
    assert result['observed_seconds'] == 8
    assert result['metrics'] == {'db': {'count': 10, 'seconds': 1}}
    assert result['pool_counters'] == {'requests_num': 10}
    assert result['maximum_waiting_requests'] == 2
    assert result['status'] == 'observed'


@pytest.mark.parametrize('after', [{'calls': 3}, {}, {'calls': 7, 'new_counter': -1}])
def test_counter_reset_is_not_reported_as_valid_work(after: dict) -> None:
    assert counter_changes({'calls': 5}, after) is None


def test_new_counters_start_at_zero_without_losing_their_first_events() -> None:
    assert counter_changes({'calls': 5}, {'calls': 7, 'new_counter': 2}) == {'calls': 2, 'new_counter': 2}


def test_missing_diagnostics_are_insufficient_evidence_not_zero_work() -> None:
    assert runtime_summary([], 10, 20)['status'] == 'insufficient_samples'
    assert postgres_summary([], 10, 20)['status'] == 'insufficient_samples'
    assert container_summary([], 10, 20)['containers'] == {}


def test_wait_occupancy_uses_observed_intervals_and_preserves_wait_categories() -> None:
    rows = [{'epoch': 11, 'cumulative': {'calls': 10}, 'active_wait_categories': {'Lock': 2, 'CPU': 1}},
            {'epoch': 13, 'cumulative': {'calls': 20}, 'active_wait_categories': {'IO': 1}},
            {'epoch': 14, 'cumulative': {'calls': 21}, 'active_wait_categories': {}}]
    result = postgres_summary(rows, 10, 20)
    assert result['counters'] == {'calls': 11}
    assert result['sampled_active_backend_seconds_by_wait_category'] == {'Lock': 4, 'CPU': 2, 'IO': 1}
    assert result['observed_seconds'] == 3


def test_container_summary_preserves_failures_and_multicore_cpu_values() -> None:
    rows = [{'epoch': 11, 'ok': True, 'containers': {'app': {'cpu_percent': 140, 'memory_bytes_approx': 50, 'pids': 4}}},
            {'epoch': 12, 'ok': False, 'error_type': 'DockerExit'},
            {'epoch': 13, 'ok': True, 'containers': {'app': {'cpu_percent': 60, 'memory_bytes_approx': 70, 'pids': 3}}}]
    result = container_summary(rows, 10, 20)
    assert result['failed_samples'] == 1
    assert result['containers']['app'] == {'samples': 2, 'mean_cpu_percent': 100, 'max_cpu_percent': 140,
                                          'max_memory_bytes_approx': 70, 'max_pids': 4}


def test_partial_last_append_does_not_discard_previous_samples(tmp_path: Path) -> None:
    path = tmp_path / 'samples.jsonl'
    path.write_text('{"epoch":1}\n{"epoch":', encoding='utf-8')
    assert read_samples(path) == [{'epoch': 1}]
    path.write_text('{"epoch":1}\nbroken\n', encoding='utf-8')
    with pytest.raises(json.JSONDecodeError):
        read_samples(path)


@pytest.mark.parametrize('value,expected', [('1.5GiB', 1610612736), (' 2.5 MB ', 2500000), ('0B', 0)])
def test_memory_units_retain_docker_format_precision(value: str, expected: int) -> None:
    assert memory_bytes(value) == expected


@pytest.mark.parametrize('change', [{'ID': 'b' * 64}, {'CPUPerc': 'NaN%'}, {'MemUsage': 'unknown'}, {'PIDs': '-1'}])
def test_invalid_or_unrequested_docker_samples_are_rejected(change: dict) -> None:
    row = {'ID': 'a' * 64, 'CPUPerc': '125%', 'MemUsage': '1MiB / 2GiB', 'PIDs': '5'} | change
    with pytest.raises((ValueError, KeyError)):
        decode_statistics(json.dumps(row), {'app': 'a' * 64})


def test_sampler_records_safe_failure_and_flushes_on_shutdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called = Event()

    def fail(*args, **kwargs) -> subprocess.CompletedProcess:
        called.set()
        return subprocess.CompletedProcess(args[0], 1, '', 'credential must never be stored')

    monkeypatch.setattr('tests.performance.resource_monitor.subprocess.run', fail)
    path = tmp_path / 'containers.jsonl'
    with sample_containers({'app': 'a' * 64}, path):
        assert called.wait(2)
    raw = path.read_text(encoding='utf-8')
    assert 'credential' not in raw
    rows = read_samples(path)
    assert len(rows) == 1 and rows[0]['ok'] is False and rows[0]['exit_code'] == 1


def test_successful_sample_strips_unneeded_docker_fields() -> None:
    row = {'ID': 'a' * 64, 'CPUPerc': '125%', 'MemUsage': '1MiB / 2GiB', 'PIDs': '5',
           'Name': 'unused container name', 'unrequested': 'must not be retained'}
    assert decode_statistics(json.dumps(row), {'app': 'a' * 64}) == {
        'app': {'cpu_percent': 125, 'memory_bytes_approx': 1048576,
                'memory_limit_bytes_approx': 2147483648, 'pids': 5},
    }
