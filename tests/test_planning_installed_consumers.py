"""Interact with released web/Python examples using only installed artifacts."""

from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import sysconfig
import tarfile
from threading import Thread
import time
from urllib.error import URLError
from urllib.request import urlopen
import venv

import pytest

from tests.test_planning_distributions import planning_artifacts

playwright_api = pytest.importorskip("playwright.sync_api")
expect = playwright_api.expect


@pytest.fixture(scope="module")
def installed_web_example(planning_artifacts: dict[str, Path]) -> Iterator[str]:
    """Serve the archive's actual example without repository files or paths."""
    directory = planning_artifacts["directory"] / "web-example"
    with tarfile.open(planning_artifacts["browser"]) as archive:
        archive.extractall(directory, filter="data")
    with ThreadingHTTPServer(("127.0.0.1", 0), partial(
        SimpleHTTPRequestHandler, directory=str(directory),
    )) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield (f"http://127.0.0.1:{server.server_port}/"
                   "planning-view-0.1.0/examples/index.html")
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_installed_web_example_edits_resources_and_unmount_remount(
    installed_web_example: str,
) -> None:
    """Both mounted instances stay isolated through writes, commands and disposal."""
    with playwright_api.sync_playwright() as driver:
        browser = driver.chromium.launch(
            executable_path=os.environ.get("EPPM_BENCHMARK_BROWSER"),
        )
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 2000})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(installed_web_example)
            secondary = page.locator("#secondary")
            secondary.locator('[data-mode="Month"]').click()
            primary = page.locator("#primary")
            primary.locator('.planning-bar[data-target-id="design"]').press("Enter")
            editor = primary.locator(".planning-editor")
            editor.locator('[data-field="name"]').fill("Reject")
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(editor.get_by_role("alert")).to_have_text("The example rejected this change.")
            editor.locator('[data-field="name"]').fill("Accepted web")
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(editor).to_be_hidden()
            expect(page.locator("#accepted")).to_have_text("Accepted edits: 1")
            expect(secondary.locator('[data-mode="Month"]')).to_have_attribute("aria-pressed", "true")
            expect(secondary.locator('.planning-bar[data-target-id="design"]')).to_have_attribute("aria-label", "Design · 2026-01-01 → 2026-01-05")
            cell = primary.locator('.planning-resource-cell[data-scope="total"]').first
            cell.click()
            expect(page.locator("#feedback")).to_contain_text("Selected engineering")
            cell.press("Shift+F10")
            page.get_by_role("menuitem", name="Mark resource period", exact=True).click()
            expect(primary.locator('[data-part="resource-filter"]')).to_be_visible()
            page.get_by_role("button", name="Unmount primary", exact=True).click()
            expect(primary.locator(".planning-view")).to_have_count(0)
            page.get_by_role("button", name="Mount primary", exact=True).click()
            page.get_by_role("button", name="Mount primary", exact=True).click()
            expect(primary.locator(".planning-view")).to_have_count(1)
            primary.locator('.planning-bar[data-target-id="design"]').press("Enter")
            editor.locator('[data-field="name"]').fill("Remounted")
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(page.locator("#accepted")).to_have_text("Accepted edits: 2")
            page.get_by_label("Load tasks on demand").check()
            expect(primary.locator('.planning-bar[data-target-id="design"]')).to_be_attached()
            page.get_by_role("button", name="Reset primary", exact=True).click()
            expect(primary.locator('[data-mode="Quarter"]')).to_have_attribute("aria-pressed", "true")
            assert errors == []
        finally:
            browser.close()


def _isolated_runtime(directory: Path, installed: Path) -> tuple[Path, dict[str, str]]:
    """Use installed third-party dependencies without their editable import hooks."""
    environment_root = directory / "runtime"
    venv.EnvBuilder(with_pip=False).create(environment_root)
    dependencies = directory / "site-packages"
    dependencies.mkdir()
    for entry in Path(sysconfig.get_path("purelib")).iterdir():
        if (entry.name.startswith((".", "__editable__", "eppm_demo",
                                   "streamlit_planning_view"))
                or entry.name in ("app", "scripts", "tests", "__pycache__")
                or entry.suffix in (".pth", ".egg-link")):
            continue
        (dependencies / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(installed), str(dependencies)))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    python = environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    probe = subprocess.run([
        str(python), "-c",
        "import importlib.util,pathlib,streamlit_planning_view as p;"
        "assert importlib.util.find_spec('app') is None;"
        "assert pathlib.Path(p.__file__).is_relative_to(pathlib.Path(__import__('sys').argv[1]))",
        str(installed),
    ], cwd=directory, env=environment, capture_output=True, text=True, timeout=15)
    assert probe.returncode == 0, probe.stderr[-2000:]
    return python, environment


@pytest.fixture(scope="module", params=["direct", "rebuilt"])
def installed_streamlit_example(
    planning_artifacts: dict[str, Path], request: pytest.FixtureRequest,
) -> Iterator[str]:
    """Run each installed wheel in a clean Python environment outside the checkout."""
    artifact = str(request.param)
    directory = planning_artifacts["directory"] / ("consumer-" + artifact)
    directory.mkdir()
    installed = directory / "installed"
    subprocess.run([
        sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
        "--target", str(installed), str(planning_artifacts[artifact]),
    ], cwd=directory, check=True, capture_output=True, text=True, timeout=45)
    python, environment = _isolated_runtime(directory, installed)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with (directory / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([
            str(python), "-m", "streamlit_planning_view",
            "--server.address=127.0.0.1", f"--server.port={port}",
            "--server.headless=true", "--browser.gatherUsageStats=false",
            "--server.fileWatcherType=none",
        ], cwd=directory, env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            origin = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urlopen(origin + "/_stcore/health", timeout=1) as reply:
                        if reply.status == 200:
                            break
                except (URLError, TimeoutError):
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Installed Streamlit example failed") from None
                    time.sleep(.1)
            yield origin
        finally:
            process.terminate()
            process.wait(timeout=10)


def test_installed_streamlit_example_handles_edits_resource_events_and_lazy_reads(
    installed_streamlit_example: str,
) -> None:
    """Direct/source-built wheels supply all modules and complete native interactions."""
    with playwright_api.sync_playwright() as driver:
        browser = driver.chromium.launch(
            executable_path=os.environ.get("EPPM_BENCHMARK_BROWSER"),
        )
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 2200})
            page.goto(installed_streamlit_example)
            frames = page.frame_locator('iframe[title="streamlit_planning_view.planning_view"]')
            primary, secondary = frames.nth(0), frames.nth(1)
            expect(primary.locator('.planning-bar[data-target-id="design"]')).to_be_visible(timeout=20000)
            secondary.locator('[data-mode="Month"]').click()
            primary.locator('.planning-bar[data-target-id="design"]').press("Enter")
            editor = primary.locator(".planning-editor")
            editor.locator('[data-field="name"]').fill("Reject")
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(editor.get_by_role("alert")).to_have_text("The example rejected this change.", timeout=10000)
            editor.locator('[data-field="name"]').fill("Installed accepted")
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(editor).to_be_hidden(timeout=10000)
            expect(page.get_by_text("Change accepted", exact=True)).to_be_visible()
            expect(secondary.locator('[data-mode="Month"]')).to_have_attribute("aria-pressed", "true")
            expect(secondary.locator('.planning-bar[data-target-id="design"]')).to_have_attribute("aria-label", "Design · 2026-01-01 → 2026-01-05")
            cell = primary.locator('.planning-resource-cell[data-scope="total"]').first
            cell.click()
            expect(page.get_by_text("Selected engineering", exact=False)).to_be_visible(timeout=10000)
            cell.press("Shift+F10")
            primary.get_by_role("menuitem", name="Mark resource period", exact=True).click()
            expect(primary.locator('[data-part="resource-filter"]')).to_be_visible(timeout=10000)
            page.get_by_label("Load tasks on demand", exact=True).press("Space")
            expect(page.get_by_text("Tasks loaded", exact=True)).to_be_visible(timeout=10000)
            expect(primary.locator('.planning-bar[data-target-id="design"]')).to_be_attached()
            assert page.locator('[data-testid="stException"]').count() == 0
            assert primary.locator(".planning-view").evaluate("n=>Math.ceil(n.getBoundingClientRect().height)<=innerHeight+1")
        finally:
            browser.close()
