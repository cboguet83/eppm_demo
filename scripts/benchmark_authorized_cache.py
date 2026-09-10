"""Compare original and compact cache hits using synthetic access scopes.

Run with ``python -m scripts.benchmark_authorized_cache``. No database, login,
project records or credentials are accessed. Timings exclude profiler overhead
and include fingerprint construction, cache lookup and result deserialization.
"""

from functools import wraps
from inspect import signature
import json
import logging
from statistics import median
from time import perf_counter_ns

import streamlit as st

from app.presentation.components.authorized_cache import authorized_cache


class _Owner:
    def __init__(self, size: int) -> None:
        self.value = ("synthetic.db", "epoch", 7, 3, ("user", "session"), tuple(range(size)))
        self.checks = 0
        self.reads = 0

    def revision(self) -> tuple:
        self.checks += 1
        return self.value


def _original_cache(**options):
    """Freeze the pre-change implementation for repeatable A/B measurements."""
    def decorate(function):
        parameters = signature(function)
        cached = st.cache_data(**options)(function)

        @wraps(function)
        def guarded(*args, **kwargs):
            values = parameters.bind(*args, **kwargs)
            owner = values.arguments.get("_workspace") or values.arguments.get("_service")
            if owner is None:
                raise ValueError("Protected caching requires an injected revision owner.")
            current = owner.revision()
            values.arguments["revision"] = (values.arguments["revision"], current)
            return cached(*values.args, **values.kwargs)

        guarded.clear = cached.clear
        return guarded
    return decorate


def _measure(decorator, size: int, planning: bool) -> dict:
    owner = _Owner(size)
    options = {"show_spinner": False}
    if planning:
        options["hash_funcs"] = {tuple: repr}

    @decorator(**options)
    def load(revision, template_id, locale, _service):
        _service.reads += 1
        return {"template": template_id, "locale": locale}

    load.clear()
    revision = owner.value if planning else ()
    assert load(revision, 1, "en", owner) == {"template": 1, "locale": "en"}
    samples = []
    for _ in range(31):
        start = perf_counter_ns()
        result = load(revision, 1, "en", owner)
        samples.append((perf_counter_ns() - start) / 1_000_000)
        assert result == {"template": 1, "locale": "en"}
    assert owner.checks == 32 and owner.reads == 1
    load.clear()
    return {"median_ms": round(median(samples), 3), "p95_ms": round(sorted(samples)[29], 3),
            "authorization_checks": owner.checks, "data_reads": owner.reads}


def main() -> None:
    """Emit aggregate timings for ordinary and already-optimized planning caches."""
    for name in ("streamlit.runtime.caching.cache_data_api", "streamlit.runtime.scriptrunner_utils.script_run_context"):
        logging.getLogger(name).setLevel(logging.ERROR)
    for size in (100, 5000, 10000):
        for planning in (False, True):
            for label, decorator in (("original", _original_cache), ("compact", authorized_cache)):
                print(json.dumps({"variant": label, "scope_size": size,
                                  "cache": "planning" if planning else "details",
                                  **_measure(decorator, size, planning)}), flush=True)


if __name__ == "__main__":
    main()
