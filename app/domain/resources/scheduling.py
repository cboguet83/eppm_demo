"""Resolve relative allocations from current owner dates without storing dates."""

from datetime import date, timedelta


def relative_period(
    start: str, end: str, anchor: str, offset_days: int, duration_days: int,
) -> tuple[str, str]:
    """Apply a signed calendar offset and an inclusive duration to an anchor.

    A positive offset always moves forward, including when anchored to the end.
    """
    first = date.fromisoformat(start if anchor == "start" else end)
    first += timedelta(days=offset_days)
    last = first + timedelta(days=duration_days - 1)
    return first.isoformat(), last.isoformat()
