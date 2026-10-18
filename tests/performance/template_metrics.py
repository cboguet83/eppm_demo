"""Opt-in preparation and outcome measurements for controlled comparisons."""

from collections.abc import Generator
import json
import os
from pathlib import Path
from time import perf_counter

import pytest


OUTPUT_VARIABLE = "EPPM_TEST_MEASUREMENT_DIRECTORY"
GROUP_SUFFIX = "@browser-benchmark-deployment"


def pytest_configure(config: pytest.Config) -> None:
    """Register explicit measurements without affecting ordinary test runs.

    Args:
        config: The current pytest invocation or worker configuration.

    Raises:
        pytest.UsageError: No output directory or stale measurements exist.
    """
    value = os.environ.get(OUTPUT_VARIABLE)
    if not value:
        raise pytest.UsageError(f"Measurements require {OUTPUT_VARIABLE}.")
    directory = Path(value).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise pytest.UsageError(
            "Measurements require a fresh output directory."
        )
    config.pluginmanager.register(_Measurements(config, directory))


class _Measurements:
    """Keep per-process measurements without fixture values or URLs."""

    def __init__(self, config: pytest.Config, directory: Path) -> None:
        self._config = config
        self._directory = directory
        self._collected: list[str] = []
        self._preparations: list[dict[str, object]] = []
        self._reports: list[dict[str, str]] = []
        self._collection_reports: list[dict[str, str]] = []
        self._subtests: list[str] = []

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_fixture_setup(
        self, fixturedef: pytest.FixtureDef[object],
        request: pytest.FixtureRequest,
    ) -> Generator[None, object, object]:
        """Time empty/migrated preparation, including a cold template."""
        if fixturedef.argname not in {"pg_database", "empty_database"}:
            return (yield)
        started = perf_counter()
        try:
            return (yield)
        finally:
            self._preparations.append({
                "fixture": fixturedef.argname,
                "nodeid": request.node.nodeid.removesuffix(GROUP_SUFFIX),
                "seconds": perf_counter() - started,
            })

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        """Record the complete local canonical collection before scheduling."""
        self._collected = [item.nodeid.removesuffix(GROUP_SUFFIX)
                           for item in session.items]

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        """Record collection failures/skips without reasons or payloads."""
        if report.passed:
            return
        self._collection_reports.append({
            "nodeid": report.nodeid, "outcome": report.outcome,
        })

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Retain phase outcomes and count subtests separately."""
        if hasattr(report, "context"):
            self._subtests.append(report.outcome)
            return
        self._reports.append({
            "nodeid": report.nodeid.removesuffix(GROUP_SUFFIX),
            "phase": report.when, "outcome": report.outcome,
        })

    def pytest_sessionfinish(self, exitstatus: int) -> None:
        """Atomically export one process record to its fresh run directory."""
        worker = getattr(self._config, "workerinput", {}).get("workerid")
        if worker is None:
            worker = ("controller" if self._config.getoption(
                "numprocesses", default=0,
            ) else "serial")
        temporary = self._directory / f"{worker}.json.tmp"
        target = self._directory / f"{worker}.json"
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump({
                "worker": worker,
                "mode": self._config.getoption("postgres_test_db_mode"),
                "collected": self._collected,
                "preparations": self._preparations,
                "reports": self._reports,
                "collection_reports": self._collection_reports,
                "subtests": self._subtests,
                "pytest_exitstatus": int(exitstatus),
            }, stream)
        temporary.replace(target)
