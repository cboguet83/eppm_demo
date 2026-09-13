"""Allowlisted Chromium processing counters; never retain trace or page content."""

import asyncio
import math
from statistics import mean
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import CDPSession


COUNTERS = {
    "LayoutDuration": "layout_seconds",
    "RecalcStyleDuration": "style_seconds",
    "ScriptDuration": "script_seconds",
    "TaskDuration": "task_seconds",
    "LayoutCount": "layouts",
    "RecalcStyleCount": "style_recalculations",
}


async def read_metrics(session: "CDPSession | None") -> dict:
    """Read numeric target counters, preserving unavailable/failed observations."""
    from playwright.async_api import Error

    if session is None:
        return {"status": "unavailable"}
    try:
        result = await asyncio.wait_for(session.send("Performance.getMetrics"), timeout=5)
        values = {item["name"]: item["value"] for item in result["metrics"]
                  if item["name"] in COUNTERS or item["name"] == "Timestamp"}
        if values.keys() != COUNTERS.keys() | {"Timestamp"} or any(
            type(value) not in {int, float} or not math.isfinite(value) or value < 0
            for value in values.values()
        ):
            return {"status": "invalid_counters"}
        return {"status": "observed", "timestamp": values.pop("Timestamp"),
                "counters": {COUNTERS[name]: value for name, value in values.items()}}
    except (Error, TimeoutError, KeyError, TypeError) as error:
        return {"status": "failed", "error_type": type(error).__name__}


def metric_delta(before: dict, after: dict) -> dict:
    """Keep workflow windows distinct from browser-action-to-result latency."""
    if before["status"] != "observed" or after["status"] != "observed":
        return {"status": "insufficient_samples", "before": before["status"], "after": after["status"]}
    changes = {name: after["counters"][name] - value for name, value in before["counters"].items()}
    interval = after["timestamp"] - before["timestamp"]
    if interval < 0 or any(value < 0 for value in changes.values()):
        return {"status": "counter_reset"}
    return {"status": "observed", "observed_seconds": interval, "counters": changes}


def summarize_browser(samples: list[dict]) -> dict:
    """Report processing separately per scenario, including failed workflows."""
    groups = {}
    for sample in samples:
        groups.setdefault(sample["scenario"], []).append(sample)
    result = {}
    for scenario, rows in groups.items():
        observations = [row["browser_processing"] for row in rows
                        if row.get("browser_processing", {}).get("status") == "observed"]
        result[scenario] = {
            "attempts": len(rows), "observed_workflows": len(observations),
            "unobserved_workflows": len(rows) - len(observations),
            "failed_workflows": sum(not row["ok"] for row in rows),
            "counters": {name: {"sum": sum(row["counters"][name] for row in observations),
                                "mean": mean(row["counters"][name] for row in observations),
                                "max": max(row["counters"][name] for row in observations)}
                         for name in COUNTERS.values()} if observations else {},
        }
    return result
