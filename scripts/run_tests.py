"""Run explicitly scoped local feedback without claiming full acceptance."""

import argparse
import logging
import os
from pathlib import Path
import shlex
import subprocess
import sys

from scripts.test_inventory import ROOT, load_inventory, test_path as validate_path


LOGGER = logging.getLogger(__name__)


def commands(mode: str, paths: list[str], root: Path = ROOT) -> list[list[str]]:
    """Build validated argument lists for partial feedback.

    Args:
        mode: Fast or explicitly targeted selection.
        paths: Repository test paths/node IDs for targeted feedback.
        root: Repository root for inventory/path validation.

    Returns:
        Commands executed in sequence, without a shell.

    Raises:
        ValueError: The mode or selected paths are invalid.
    """
    base = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if mode == "fast" and not paths:
        return [[*base, "-p", "scripts.fast_test_guard", *load_inventory(root)]]
    if mode == "targeted" and paths:
        return [[*base, *[validate_path(value, root) for value in paths]]]
    raise ValueError("Choose fast without paths, or targeted with explicit test paths.")


def run_commands(
    selected: list[list[str]], root: Path, environment: dict[str, str],
) -> int:
    """Run each command and preserve its first failure or interruption status."""
    for command in selected:
        result = subprocess.run(command, cwd=root, env=environment, check=False)
        if result.returncode:
            return result.returncode if result.returncode > 0 else 128 - result.returncode
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run partial feedback with explicit selection and safe diagnostic output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fast", "targeted"))
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        selected = commands(args.mode, args.paths)
        environment = dict(os.environ)
        if environment.get("PYTEST_ADDOPTS", "").strip():
            raise ValueError("Unset PYTEST_ADDOPTS; scope must be explicit.")
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
        return run_commands(selected, ROOT, environment)
    except (OSError, ValueError) as error:
        LOGGER.error("Test runner could not start: %s", error)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
