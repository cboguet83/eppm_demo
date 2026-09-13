"""Do not let fast requests or missing samples conceal a failing load scenario."""

import asyncio
from types import SimpleNamespace

import pytest

from tests.performance import browser_load
from tests.performance.browser_load import summarize


def test_slow_scenario_is_not_hidden_by_many_fast_other_requests() -> None:
    samples = [{"scenario": "portfolio_paging", "ok": True, "elapsed_ms": 10} for _ in range(100)]
    samples += [{"scenario": "simple_save", "ok": True, "elapsed_ms": value}
                for value in (100, 200, 1500)]
    result = summarize(samples)
    assert result["portfolio_paging"]["p95_ms"] == 10
    assert result["simple_save"]["p95_ms"] == 1500
    assert result["visible_task_loading"] == {
        "attempts": 0, "failures": 0, "successes": 0, "p95_ms": None, "max_ms": None,
    }


def test_failed_actions_remain_visible_without_fabricated_fast_latency() -> None:
    samples = [
        {"scenario": "visible_task_loading", "ok": True, "elapsed_ms": 250},
        {"scenario": "visible_task_loading", "ok": False, "error_type": "TimeoutError"},
    ]
    assert summarize(samples)["visible_task_loading"] == {
        "attempts": 2, "failures": 1, "successes": 1, "p95_ms": 250, "max_ms": 250,
    }


def test_nearest_rank_percentile_includes_the_required_ninety_fifth_sample() -> None:
    samples = [{"scenario": "simple_save", "ok": True, "elapsed_ms": value} for value in range(1, 101)]
    assert summarize(samples)["simple_save"]["p95_ms"] == 95


def test_failed_worker_keeps_offering_actions_and_failed_diagnostics_do_not_erase_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def action(session) -> float:
        calls.append(session.sequence)
        if len(calls) == 1:
            raise RuntimeError('original workflow failure')
        return 10

    class BrokenPage:
        def locator(self, selector):
            raise ValueError('diagnostic unavailable')

    monkeypatch.setitem(browser_load.OPERATIONS, 'portfolio_paging', action)
    session = SimpleNamespace(index=0, scenario='portfolio_paging', sequence=0, page=BrokenPage())
    samples = []
    phase = asyncio.run(browser_load._period([session], browser_load.Options(cadence_seconds=.01), .1, 1, False, samples))
    assert len(calls) >= 2
    assert samples[0]['ok'] is False and samples[0]['error_type'] == 'RuntimeError'
    assert samples[0]['diagnostic_error_type'] == 'ValueError'
    assert all(sample['ok'] for sample in samples[1:])
    assert phase['ended_epoch'] >= phase['started_epoch']
