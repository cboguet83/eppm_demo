"""Lossless interval encoding for repeated daily pool values on the chart wire."""

from datetime import date
from typing import Any


def pack_pool_payloads(pools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Encode the dynamic chart JSON boundary without dropping zeroes or gaps."""
    result = []
    for pool in pools:
        packed = dict(pool)
        packed.pop("overallocated_dates", None)
        packed.pop("selected_projects_overallocated_dates", None)
        for field in ("daily_usage", "daily_assigned_capacity", "selected_projects_daily_usage"):
            intervals = []
            previous = None
            for day, value in sorted(packed.pop(field, {}).items()):
                ordinal = date.fromisoformat(day).toordinal()
                if intervals and ordinal == previous + 1 and intervals[-1][2] == value:
                    intervals[-1][1] = day
                else:
                    intervals.append([day, day, value])
                previous = ordinal
            packed[field + "_intervals"] = intervals
        result.append(packed)
    return result
