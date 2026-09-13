"""Counter gaps and failures must not be presented as zero browser work."""

import asyncio
from types import SimpleNamespace

import pytest

from tests.performance.browser_metrics import COUNTERS, metric_delta, read_metrics, summarize_browser


def observation(value: float, timestamp: float = 10) -> dict:
    return {"status": "observed", "timestamp": timestamp,
            "counters": {name: value for name in COUNTERS.values()}}


def test_browser_counters_are_differenced_with_their_own_window() -> None:
    result = metric_delta(observation(100, 10), observation(101, 12))
    assert result == {"status": "observed", "observed_seconds": 2,
                      "counters": {name: 1 for name in COUNTERS.values()}}


@pytest.mark.parametrize("after", [observation(99, 12), observation(101, 9)])
def test_browser_counter_or_clock_reset_is_not_valid_processing(after: dict) -> None:
    assert metric_delta(observation(100), after) == {"status": "counter_reset"}


def test_missing_browser_metrics_are_not_zero_work() -> None:
    assert asyncio.run(read_metrics(None)) == {"status": "unavailable"}
    assert metric_delta({"status": "failed"}, observation(1))["status"] == "insufficient_samples"


@pytest.mark.parametrize("invalid", [None, -1, float("nan"), "credential value"])
def test_invalid_browser_values_cannot_enter_evidence(invalid) -> None:
    async def send(command):
        return {"metrics": [{"name": name, "value": invalid if name == "LayoutDuration" else 1}
                            for name in [*COUNTERS, "Timestamp"]]}
    assert asyncio.run(read_metrics(SimpleNamespace(send=send))) == {"status": "invalid_counters"}


def test_browser_metrics_strip_unrequested_fields_and_preserve_safe_errors() -> None:
    async def send(command):
        return {"metrics": [{"name": name, "value": 1} for name in [*COUNTERS, "Timestamp"]]
                           + [{"name": "Unrequested", "value": "must not be retained"}]}
    assert asyncio.run(read_metrics(SimpleNamespace(send=send))) == observation(1, 1)

    async def fail(command):
        raise TimeoutError("must not be retained")
    assert asyncio.run(read_metrics(SimpleNamespace(send=fail))) == {"status": "failed", "error_type": "TimeoutError"}


def test_browser_summary_keeps_scenarios_and_failed_workflows_separate() -> None:
    observed = metric_delta(observation(1), observation(3, 12))
    result = summarize_browser([
        {"scenario": "save", "ok": False, "browser_processing": observed},
        {"scenario": "save", "ok": True, "browser_processing": {"status": "counter_reset"}},
        {"scenario": "page", "ok": True, "browser_processing": observed},
    ])
    assert result["save"]["attempts"] == 2
    assert result["save"]["failed_workflows"] == result["save"]["unobserved_workflows"] == 1
    assert result["save"]["counters"]["layout_seconds"] == {"sum": 2, "mean": 2, "max": 2}
    assert result["page"]["attempts"] == 1


def test_real_chromium_reports_layout_and_style_processing_without_page_content() -> None:
    from playwright.async_api import async_playwright

    async def measure() -> dict:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                session = await page.context.new_cdp_session(page)
                await session.send("Performance.enable", {"timeDomain": "timeTicks"})
                before = await read_metrics(session)
                await page.set_content("<div id='box'>Fictional measurement content</div>")
                await page.evaluate("""() => {
                    const box = document.getElementById('box');
                    for (let width = 100; width < 105; width++) {
                        box.style.width = width + 'px';
                        box.getBoundingClientRect();
                    }
                }""")
                return metric_delta(before, await read_metrics(session))
            finally:
                await browser.close()

    result = asyncio.run(measure())
    assert result["status"] == "observed"
    assert result["observed_seconds"] > 0
    assert result["counters"]["layouts"] > 0
    assert result["counters"]["style_recalculations"] > 0
    assert result["counters"]["layout_seconds"] > 0
    assert result["counters"]["style_seconds"] > 0
