"""Explicit reference capture for planning extraction, outside default collection.

Run this module explicitly with pytest and a new ignored --basetemp directory.
Reports contain fixture metrics only; database credentials stay in child env.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from playwright.async_api import async_playwright

from app.infrastructure.postgresql.backup import PostgresTools
from scripts.benchmark_planning import create_app, run_app
from scripts.benchmark_runtime import isolated_benchmark
from tests.postgresql.business import business  # noqa: F401 - registers fixture
from tests.postgresql.conftest import PostgreSQLFixture
from tests.postgresql.test_benchmark_tools import copies, snapshot


@pytest.mark.usefixtures("business")
@pytest.mark.parametrize("mode", ["collapsed", "expanded", "external", "native"])
@pytest.mark.parametrize("iteration", range(1, 6))
def test_capture_reference(
    mode: str,
    iteration: int,
    pg_database: PostgreSQLFixture,
    tmp_path: Path,
) -> None:
    """Capture repeated browser metrics and verify disposable source isolation."""
    import asyncio

    async def executable() -> str:
        """Resolve installed Chromium and let its driver initialize cleanly."""
        async with async_playwright() as playwright:
            result = playwright.chromium.executable_path
            await asyncio.sleep(0)
            return result

    command = ["node", "scripts/benchmark_gantt.cjs", asyncio.run(executable())]
    if mode in {"expanded", "external", "native"}:
        command.append("--expanded")
    if mode == "external":
        command.append("--external-links")
    environment = os.environ | {"EPPM_BENCHMARK_PYTHON": sys.executable}
    if mode == "native":
        command.extend(["--database", "--all-projects"])
        environment.update(DATABASE_OPERATOR_URL=pg_database.operator_url,
                           DATABASE_URL=pg_database.runtime_url)
        if container := os.environ.get("POSTGRES_TEST_CLIENT_CONTAINER"):
            command.append("--client-container=" + container)
    before = snapshot(pg_database)
    completed = subprocess.run(command, env=environment, capture_output=True,
                               text=True, timeout=180, check=False)
    assert completed.returncode == 0, completed.stderr[-3000:]
    report = json.loads(completed.stdout)
    assert report["resourceRows"] > 0
    assert report["resourceRows"] <= 40
    assert report["resourceCells"] > 0
    assert report["resourcePaneAlignmentPx"] <= 1
    assert snapshot(pg_database) == before
    with (tmp_path / "metrics.json").open("w", encoding="utf-8") as output:
        json.dump({"mode": mode, "iteration": iteration, "metrics": report},
                  output, indent=2)


@pytest.mark.usefixtures("business")
@pytest.mark.parametrize("iteration", range(1, 6))
def test_capture_host_edit(
    iteration: int,
    pg_database: PostgreSQLFixture,
    clients: PostgresTools,
    tmp_path: Path,
) -> None:
    """Measure actual date-edit preparation using a disposable native restore."""
    before = snapshot(pg_database)
    with isolated_benchmark(pg_database.operator_url, pg_database.runtime_url,
                            tools=clients) as context:
        app = create_app(context, projects=0, profile=False, capture=True)
        run_app(app)
        app.session_state["benchmark_event"] = {
            "action": "toggle_edit", "enabled": True, "nonce": "reference-enable",
        }
        run_app(app)
        app.session_state["benchmark_event"] = {
            "action": "load_project_tasks", "project_ids": [1, 2],
            "scope_token": app.session_state["planning_chart_snapshot"]["token"],
            "nonce": "reference-load",
        }
        run_app(app)
        app.session_state["benchmark_event"] = {
            "action": "update_dates", "id": 10, "start_date": "2026-01-02",
            "end_date": "2026-01-06", "nonce": "reference-edit",
        }
        run_app(app)
        report = {"server_seconds": app.session_state["benchmark_seconds"],
                  "payload_bytes": len(json.dumps(app.session_state["benchmark_payload"]).encode())}
    assert snapshot(pg_database) == before
    assert context.name not in copies(pg_database)
    with (tmp_path / "metrics.json").open("w", encoding="utf-8") as output:
        json.dump({"mode": "native-edit", "iteration": iteration,
                   "metrics": report}, output, indent=2)
