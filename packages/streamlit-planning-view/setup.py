"""Reject incomplete standalone distributions before packaging."""

from collections.abc import Callable
from pathlib import Path
from runpy import run_path
from typing import cast

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.editable_wheel import editable_wheel
from setuptools.command.sdist import sdist

# Load the trusted build validator without relying on source-root imports.
ROOT = Path(__file__).resolve().parent
VALIDATE_FRONTEND = cast(
    Callable[[Path], None],
    run_path(str(ROOT / "build_frontend.py"))["validate_frontend"],
)


class CheckedBuild(build_py):
    """Verify prepared resources before building package data."""

    def run(self) -> None:
        """Validate the complete local source and build its wheel tree."""
        VALIDATE_FRONTEND(ROOT)
        super().run()


class CheckedSource(sdist):
    """Keep the prepared frontend inside independently rebuildable sources."""

    def run(self) -> None:
        """Validate prepared assets before source-distribution assembly."""
        VALIDATE_FRONTEND(ROOT)
        super().run()


class CheckedEditable(editable_wheel):
    """Keep development installation subject to the same resource checks."""

    def run(self) -> None:
        """Validate prepared assets before editable wheel assembly."""
        VALIDATE_FRONTEND(ROOT)
        super().run()


setup(cmdclass={
    "build_py": CheckedBuild, "sdist": CheckedSource,
    "editable_wheel": CheckedEditable,
})
