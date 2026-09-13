"""Do not let fast requests or missing samples conceal a failing load scenario."""

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
