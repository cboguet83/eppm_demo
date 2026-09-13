"""Passive timing hooks mounted only in disposable benchmark containers.

The wrappers preserve arguments, return values and exceptions. Dynamic wrappers
use Any because the instrumented libraries expose different call signatures.
No queries, parameters, identities, cookies, URLs or exception messages are stored.
"""

from collections.abc import Callable
import atexit
from functools import wraps
import json
import os
from pathlib import Path
import resource
import threading
from time import perf_counter, time
import traceback
from typing import Any
import weakref


_lock = threading.Lock()
_totals: dict[str, dict[str, float | int]] = {}
_pools = weakref.WeakSet()
_failures: list[dict[str, object]] = []


def record(name: str, seconds: float) -> None:
    """Accumulate elapsed wall time and counts without per-query filesystem I/O."""
    with _lock:
        metric = _totals.setdefault(name, {"count": 0, "seconds": 0.0, "max_seconds": 0.0})
        metric["count"] += 1
        metric["seconds"] += seconds
        metric["max_seconds"] = max(metric["max_seconds"], seconds)


def timed(name: str, operation: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a synchronous library boundary without changing its semantics."""
    @wraps(operation)
    def call(*args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        try:
            return operation(*args, **kwargs)
        except Exception as error:
            if name.startswith("db_"):
                locations = [{"file":item.filename.removeprefix("/app/"), "line":item.lineno, "function":item.name}
                             for item in traceback.extract_stack() if item.filename.startswith("/app/app/")]
                with _lock:
                    _failures.append({"metric":name, "category":type(error).__name__, "locations":locations})
                    del _failures[:-20]
            raise
        finally:
            record(name, perf_counter() - started)
    return call


def _snapshot() -> dict[str, object]:
    with _lock:
        metrics = {name: dict(value) for name, value in _totals.items()}
        pools = list(_pools)
        failures = list(_failures)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {"epoch": time(), "cumulative": metrics, "database_failures":failures,
            "pools": [pool.get_stats() for pool in pools],
            "process": {"user_seconds": usage.ru_utime, "system_seconds": usage.ru_stime,
                        "max_rss_kib": usage.ru_maxrss}}


def _publish() -> None:
    path = Path("/app/data/runtime-timings.jsonl")
    with path.open("a", encoding="utf-8", buffering=1) as target:
        while True:
            target.write(json.dumps(_snapshot()) + "\n")
            threading.Event().wait(2)


def install(backend: str) -> None:
    """Observe actual Streamlit runs, HTTP readers and backend client operations."""
    from streamlit.runtime.scriptrunner.script_runner import ScriptRunner
    from app.infrastructure.authentication.planning import PlanningReadRoutes

    if os.environ.get('LOAD_PROFILE') == '1':
        from profiling import StackProfiler

        profiler = StackProfiler(Path('/app/data/thread-profiles.json'))
        profiler.start()
        atexit.register(profiler.stop)
    ScriptRunner._run_script = timed("server_script", ScriptRunner._run_script)
    original_read = PlanningReadRoutes._read
    @wraps(original_read)
    async def read(*args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        try:
            return await original_read(*args, **kwargs)
        finally:
            kind = args[3] if len(args) > 3 else kwargs.get("kind")
            record("server_http_" + (kind if kind in {"planning", "portfolio"} else "other"),
                   perf_counter() - started)
    PlanningReadRoutes._read = read

    if backend == "postgresql":
        import psycopg
        from psycopg_pool import ConnectionPool
        from app.application.services.projects import ProjectService
        from app.infrastructure.postgresql.derived_cache import PostgresDerivedCache

        ProjectService.update_project = timed('service_project_update', ProjectService.update_project)
        for method in ('read', 'publish', 'load'):
            setattr(PostgresDerivedCache, method, timed('cache_' + method, getattr(PostgresDerivedCache, method)))

        for method in ("execute", "executemany", "fetchone", "fetchmany", "fetchall"):
            setattr(psycopg.Cursor, method, timed("db_client_" + method, getattr(psycopg.Cursor, method)))
        original_init = ConnectionPool.__init__
        @wraps(original_init)
        def initialize(pool: ConnectionPool, *args: Any, **kwargs: Any) -> None:
            original_init(pool, *args, **kwargs)
            with _lock:
                _pools.add(pool)
        ConnectionPool.__init__ = initialize
        ConnectionPool.getconn = timed("pool_acquire", ConnectionPool.getconn)
    elif backend == "sqlite":
        import runpy
        runpy.run_path("/baseline-observer/observer.py")["install"](timed)
    else:
        raise ValueError("Unknown benchmark backend.")
    threading.Thread(target=_publish, name="benchmark-timings", daemon=True).start()
