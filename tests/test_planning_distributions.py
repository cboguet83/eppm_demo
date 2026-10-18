"""Build and inspect portable artifacts outside source-tree import resolution."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from threading import Thread
from types import ModuleType
from zipfile import ZipFile

import pytest

from scripts.build_planning_assets import (
    AssetError, TARGETS, browser_archive, check_assets, prepare_assets, source_files,
)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "packages/streamlit-planning-view"


def _validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "planning_build_frontend", WRAPPER / "build_frontend.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def asset_root(tmp_path: Path) -> Path:
    """Copy only canonical assets/metadata into an isolated assembly fixture."""
    shutil.copytree(ROOT / "packages/planning-view", tmp_path / "packages/planning-view")
    wrapper = tmp_path / "packages/streamlit-planning-view"
    wrapper.mkdir()
    shutil.copyfile(WRAPPER / "pyproject.toml", wrapper / "pyproject.toml")
    shutil.copyfile(ROOT / "LICENSE", tmp_path / "LICENSE")
    return tmp_path


def test_assembly_matches_all_hosts_and_browser_archive_is_reproducible(
    asset_root: Path,
) -> None:
    """Every distribution uses identical bytes and stable archive metadata."""
    prepare_assets(asset_root)
    check_assets(asset_root)
    files = source_files(asset_root)
    for relative in TARGETS.values():
        for name, content in files.items():
            assert (asset_root / relative / name).read_bytes() == content
    first, second = asset_root / "first.tar.gz", asset_root / "second.tar.gz"
    browser_archive(files, first)
    browser_archive(files, second)
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        assert all(member.mtime == 0 for member in archive.getmembers())
        assert len(archive.getmembers()) == len(files)


def test_missing_stale_versioned_and_unmanaged_assets_fail_explicitly(
    asset_root: Path,
) -> None:
    """Assembly detects drift and preserves files outside its managed outputs."""
    with pytest.raises(AssetError, match="Missing"):
        check_assets(asset_root)
    prepare_assets(asset_root)
    path = asset_root / TARGETS["eppm"] / "src/index.js"
    path.write_text("stale", encoding="utf-8")
    with pytest.raises(AssetError, match="Stale"):
        check_assets(asset_root)
    prepare_assets(asset_root)
    extra = path.parent / "unmanaged.js"
    extra.write_text("host content", encoding="utf-8")
    with pytest.raises(AssetError, match="unmanaged"):
        prepare_assets(asset_root)
    assert extra.read_text(encoding="utf-8") == "host content"
    extra.unlink()
    (asset_root / "packages/planning-view/src/index.js").unlink()
    with pytest.raises(AssetError, match="Canonical"):
        source_files(asset_root)


def test_assembly_requires_matching_versions_and_owns_only_marked_directories(
    asset_root: Path,
) -> None:
    """Source/version drift and symlink/unmarked targets never get overwritten."""
    project = asset_root / "packages/streamlit-planning-view/pyproject.toml"
    original = project.read_text(encoding="utf-8")
    project.write_text(original.replace('version = "0.1.0"', 'version = "0.2.0"'), encoding="utf-8")
    with pytest.raises(AssetError, match="versions disagree"):
        source_files(asset_root)
    project.write_text(original, encoding="utf-8")
    target = asset_root / TARGETS["eppm"]
    target.mkdir(parents=True)
    (target / "host.txt").write_text("retain", encoding="utf-8")
    with pytest.raises(AssetError, match="unmanaged"):
        prepare_assets(asset_root)
    (target / "host.txt").unlink()
    target.rmdir()
    target.symlink_to(asset_root / "packages/planning-view", target_is_directory=True)
    with pytest.raises(AssetError, match="symlink"):
        prepare_assets(asset_root)


def _backend(
    source: Path, output: Path, operation: str, *, succeeds: bool = True,
) -> subprocess.CompletedProcess[str]:
    default = (sys.executable if importlib.util.find_spec("setuptools")
               else shutil.which("python3") or sys.executable)
    python = os.environ.get("EPPM_BUILD_PYTHON", default)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["SOURCE_DATE_EPOCH"] = "315532800"
    result = subprocess.run([
        python, "-I", "-c",
        "import sys;"
        "assert sys.version_info[:2]==(3,14);"
        "from setuptools import build_meta;"
        "getattr(build_meta,sys.argv[2])(sys.argv[1])",
        str(output), operation,
    ], cwd=source, env=environment, capture_output=True, text=True, timeout=90)
    if succeeds:
        assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    else:
        assert result.returncode != 0
    return result


@pytest.mark.parametrize("project", [ROOT, WRAPPER], ids=["application", "standalone"])
def test_isolated_pep517_editable_hooks_find_their_validators(
    project: Path, tmp_path: Path,
) -> None:
    """Metadata and editable builds must work without source-root import paths."""
    prepare_assets(ROOT)
    default = (sys.executable if importlib.util.find_spec("setuptools")
               else shutil.which("python3") or sys.executable)
    python = os.environ.get("EPPM_BUILD_PYTHON", default)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [python, "-I", "-c", "from setuptools import build_meta;"
         "build_meta.get_requires_for_build_editable()"],
        cwd=project, env=environment, capture_output=True, text=True,
        timeout=90, check=False,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    _backend(project, tmp_path / "editable", "build_editable")
    assert len(list((tmp_path / "editable").glob("*.whl"))) == 1


@pytest.fixture(scope="module")
def planning_artifacts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Prepare three release forms and rebuild a wheel using only extracted sources."""
    prepare_assets(ROOT)
    directory = tmp_path_factory.mktemp("planning-artifacts")
    direct, rebuilt, application = directory / "direct", directory / "rebuilt", directory / "application"
    _backend(WRAPPER, direct, "build_wheel")
    _backend(WRAPPER, direct, "build_sdist")
    source_distribution = next(direct.glob("*.tar.gz"))
    extracted = directory / "extracted"
    with tarfile.open(source_distribution) as archive:
        archive.extractall(extracted, filter="data")
    extracted_root = next(extracted.iterdir())
    _backend(extracted_root, rebuilt, "build_wheel")
    _backend(ROOT, application, "build_wheel")
    _backend(ROOT, application, "build_sdist")
    application_source = next(application.glob("*.tar.gz"))
    application_extracted = directory / "application-extracted"
    with tarfile.open(application_source) as archive:
        archive.extractall(application_extracted, filter="data")
    application_rebuilt = directory / "application-rebuilt"
    _backend(next(application_extracted.iterdir()), application_rebuilt, "build_wheel")
    browser = directory / "browser.tar.gz"
    browser_archive(source_files(ROOT), browser)
    return {
        "directory": directory, "direct": next(direct.glob("*.whl")),
        "rebuilt": next(rebuilt.glob("*.whl")), "source": source_distribution,
        "extracted": extracted_root, "application": next(application.glob("*.whl")),
        "application-rebuilt": next(application_rebuilt.glob("*.whl")),
        "browser": browser,
    }


def test_direct_rebuilt_and_root_wheels_contain_matching_complete_assets(
    planning_artifacts: dict[str, Path],
) -> None:
    """Nested modules/styles survive all wheels with exact source manifest parity."""
    expected = source_files(ROOT)
    prefixes = {"direct": "streamlit_planning_view/frontend/",
                "rebuilt": "streamlit_planning_view/frontend/",
                "application": "app/presentation/assets/components/gantt/planning-view/",
                "application-rebuilt": "app/presentation/assets/components/gantt/planning-view/"}
    for artifact, prefix in prefixes.items():
        with ZipFile(planning_artifacts[artifact]) as wheel:
            names = {name.removeprefix(prefix) for name in wheel.namelist()
                     if name.startswith(prefix) and not name.endswith("/")}
            assert names == expected.keys()
            for name, content in expected.items():
                assert wheel.read(prefix + name) == content
            if artifact.startswith("application"):
                host = ROOT / "app/presentation/assets/components/gantt"
                for path in host.iterdir():
                    if path.is_file() and path.suffix in {".html", ".js", ".css"}:
                        assert wheel.read("app/presentation/assets/components/gantt/" + path.name) == path.read_bytes()
    _validator().validate_frontend(planning_artifacts["extracted"])


@pytest.mark.parametrize("artifact", ["direct", "rebuilt", "application", "application-rebuilt"])
def test_wheel_installs_outside_checkout_without_editable_paths(
    planning_artifacts: dict[str, Path], artifact: str,
) -> None:
    """Import installed packages and resources with source-tree resolution disabled."""
    directory = planning_artifacts["directory"] / ("installed-" + artifact)
    subprocess.run([
        sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
        "--target", str(directory), str(planning_artifacts[artifact]),
    ], cwd=planning_artifacts["directory"], capture_output=True, text=True,
        timeout=45, check=True)
    package = "app" if artifact.startswith("application") else "streamlit_planning_view"
    relative = ("presentation/assets/components/gantt/planning-view"
                if artifact.startswith("application") else "frontend")
    script = """
import hashlib,importlib,importlib.resources,json,pathlib,sys
target=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(target))
module=importlib.import_module(sys.argv[2])
assert pathlib.Path(module.__file__).is_relative_to(target)
root=importlib.resources.files(module).joinpath(sys.argv[3])
manifest=json.loads(root.joinpath('manifest.json').read_text())
for name,digest in manifest['files'].items():
    assert hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest()==digest
source=pathlib.Path(sys.argv[4]).resolve()
assert not any(pathlib.Path(entry).resolve().is_relative_to(source)
               for entry in sys.path if entry)
"""
    result = subprocess.run([
        sys.executable, "-I", "-c", script, str(directory), package, relative,
        str(ROOT),
    ], cwd=planning_artifacts["directory"], capture_output=True, text=True,
        timeout=15)
    assert result.returncode == 0, result.stderr[-2000:]


def test_standalone_build_rejects_missing_or_changed_frontend(
    planning_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    """A standalone source distribution fails its own guard without EPPM access."""
    source = tmp_path / "source"
    shutil.copytree(planning_artifacts["extracted"], source,
                    ignore=shutil.ignore_patterns("build", "*.egg-info"))
    path = source / "src/streamlit_planning_view/frontend/src/index.js"
    path.write_text("stale", encoding="utf-8")
    result = _backend(source, tmp_path / "bad-wheel", "build_wheel", succeeds=False)
    assert "checksum mismatch" in result.stderr
    path.unlink()
    with pytest.raises(ValueError, match="resources"):
        _validator().validate_frontend(source)


def test_clean_browser_archive_renders_without_eppm_sources(
    planning_artifacts: dict[str, Path],
) -> None:
    """Only extracted browser artifacts supply modules, styles and rendered cells."""
    playwright = pytest.importorskip("playwright.sync_api")
    directory = planning_artifacts["directory"] / "browser-consumer"
    with tarfile.open(planning_artifacts["browser"]) as archive:
        archive.extractall(directory, filter="data")
    with ThreadingHTTPServer(("127.0.0.1", 0), partial(
        SimpleHTTPRequestHandler, directory=str(directory),
    )) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with playwright.sync_playwright() as driver:
                browser = driver.chromium.launch(
                    executable_path=os.environ.get("EPPM_BENCHMARK_BROWSER"),
                )
                try:
                    page = browser.new_page(viewport={"width": 1300, "height": 1000})
                    page.goto(f"http://127.0.0.1:{server.server_port}")
                    page.evaluate("""async () => {
                      document.body.innerHTML='<main></main>';
                      const {mountPlanningView}=await import('/planning-view-0.1.0/src/index.js');
                      mountPlanningView(document.querySelector('main'),{today:'2026-01-01',grouped:false,
                        snapshot:{version:1,kind:'snapshot',scope:'portable',revision:'r',
                          projects:[{id:'p',name:'Project'}],tasks:[{id:'task',projectId:'p',name:'Portable task',start:'2026-01-01',end:'2026-01-03'}],
                          resources:[{id:'pool',name:'Pool',capacity:5,usage:{'2026-01-01':2}}]}});
                    }""")
                    playwright.expect(page.locator('.planning-bar[data-target-id="task"]')).to_be_visible()
                    playwright.expect(page.locator(".planning-resource-cell").first).to_be_visible()
                    assert page.locator(".planning-view").evaluate("n=>getComputedStyle(n).borderTopWidth") == "1px"
                finally:
                    browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
