"""Run explicit partial feedback or canonical complete acceptance."""

import argparse
import logging
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import tomllib

from scripts.test_inventory import ROOT, load_inventory, test_path as validate_path


LOGGER = logging.getLogger(__name__)


def commands(
    mode: str, paths: list[str], root: Path = ROOT,
    manifest: Path = Path("FULL_MANIFEST.json"),
) -> list[list[str]]:
    """Build validated argument lists for the explicitly selected test scope.

    Args:
        mode: Fast, explicitly targeted, or complete execution.
        paths: Repository test paths/node IDs for targeted feedback.
        root: Repository root for inventory/path validation.
        manifest: Fresh reference file shared by full collection/execution.

    Returns:
        Commands executed in sequence, without a shell.

    Raises:
        ValueError: The mode or selected paths are invalid.
    """
    base = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if mode == "full" and not paths:
        validate_full_config(root)
        proof = ["-c", "pyproject.toml", "-p", "scripts.full_test_proof"]
        return [
            [*base, *proof, "--collect-only", "--write-full-manifest", str(manifest), "tests"],
            [*base, *proof, "tests", "-x", "--full-manifest", str(manifest),
             "--require-full-suite", "--cov=app", "--cov-config=pyproject.toml",
             "--cov-report=term",
             "--cov-fail-under=95", "-n", "2", "--dist=loadgroup",
             "--postgres-test-db-mode=template", "--max-worker-restart=0"],
            ["node", "--test", *sorted(path.relative_to(root).as_posix()
                                     for path in (root / "tests").glob("test_*.cjs"))],
            ["node", "--test", *sorted(path.relative_to(root).as_posix()
                                     for path in (root / "packages/planning-view/tests").glob("*.test.js"))],
            [sys.executable, "-m", "scripts.build_planning_assets", "--check"],
        ]
    if mode == "fast" and not paths:
        return [[*base, "-p", "scripts.fast_test_guard", *load_inventory(root)]]
    if mode == "targeted" and paths:
        return [[*base, *[validate_path(value, root) for value in paths]]]
    raise ValueError("Fast/full take no paths; targeted needs explicit test paths.")


def validate_full_config(root: Path) -> None:
    """Reject configuration that would silently narrow full discovery/coverage.

    Args:
        root: Repository containing the canonical pyproject configuration.

    Raises:
        ValueError: Discovery or application coverage is no longer canonical.
    """
    with (root / "pyproject.toml").open("rb") as stream:
        config = tomllib.load(stream)["tool"]
    options = config["pytest"]["ini_options"]
    coverage = config["coverage"]["run"]
    if options != {"testpaths": ["tests"]}:
        raise ValueError("Full discovery requires canonical pytest configuration.")
    if coverage != {"source": ["app"], "patch": ["subprocess"], "sigterm": True}:
        raise ValueError("Full acceptance requires canonical application coverage.")
    if not list((root / "tests").glob("test_*.cjs")) or not list(
        (root / "packages/planning-view/tests").glob("*.test.js")
    ):
        raise ValueError("Both JavaScript suites are required for full acceptance.")


def require_full_environment(environment: dict[str, str]) -> None:
    """Check prerequisite names without displaying connection strings or secrets."""
    names = ("POSTGRES_TEST_ADMIN_URL", "POSTGRES_TEST_RUNTIME_URL",
             "POSTGRES_TEST_CLIENT_CONTAINER")
    missing = [name for name in names if not environment.get(name, "").strip()]
    if environment.get("EPPM_RUN_OIDC_E2E") != "1":
        missing.append("EPPM_RUN_OIDC_E2E=1")
    if missing:
        raise ValueError("Full acceptance requires: " + ", ".join(missing))


def run_commands(
    selected: list[list[str]], root: Path, environment: dict[str, str],
) -> int:
    """Run each command and preserve its first failure or interruption status."""
    for command in selected:
        collection = "--collect-only" in command
        result = subprocess.run(
            command, cwd=root, env=environment, check=False,
            capture_output=collection, text=True,
        )
        if result.returncode:
            if collection:
                LOGGER.error("Canonical collection failed; full acceptance is incomplete.")
            return result.returncode if result.returncode > 0 else 128 - result.returncode
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the selected scope, preserving failure and safe diagnostic output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fast", "targeted", "full"))
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        selected = commands(args.mode, args.paths)
        environment = dict(os.environ)
        if any(environment.get(name, "").strip()
               for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS")):
            raise ValueError("Unset PYTEST_ADDOPTS/PYTEST_PLUGINS; scope must be explicit.")
        if args.mode != "full":
            LOGGER.info("Partial %s feedback; not full acceptance or the 95%% coverage gate.", args.mode)
        if args.dry_run:
            for command in selected:
                LOGGER.info("%s", shlex.join(command))
            return 0
        if args.mode == "fast":
            environment = {name: value for name, value in environment.items()
                           if name in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR",
                                       "VIRTUAL_ENV", "SYSTEMROOT", "WINDIR",
                                       "PYTHONIOENCODING"}}
            environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        if args.mode == "full":
            require_full_environment(environment)
            if environment.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD"):
                raise ValueError("Full acceptance requires the installed coverage/xdist plugins.")
            with tempfile.TemporaryDirectory(prefix="eppm-full-") as temporary:
                selected = commands("full", [], ROOT, Path(temporary) / "canonical.json")
                LOGGER.info("Full acceptance: canonical discovery, real integrations, coverage >=95%.")
                return run_commands(selected, ROOT, environment)
        return run_commands(selected, ROOT, environment)
    except (OSError, ValueError) as error:
        LOGGER.error("Test runner could not start: %s", error)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
