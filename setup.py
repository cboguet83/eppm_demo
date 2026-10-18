"""Verify prepared planning resources before root package/source builds."""

from collections.abc import Callable
from pathlib import Path
from runpy import run_path
from typing import cast

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.editable_wheel import editable_wheel
from setuptools.command.sdist import sdist

# Isolated PEP 517 hooks do not put the source root on the import path.
ROOT = Path(__file__).resolve().parent
CHECK_ASSETS = cast(
    Callable[[Path, tuple[str, ...]], None],
    run_path(str(ROOT / "scripts/build_planning_assets.py"))["check_assets"],
)


class CheckedBuild(build_py):
    """Prevent incomplete or stale assets in installed EPPM wheels."""

    def run(self) -> None:
        """Validate the canonical embedded assets before packaging."""
        CHECK_ASSETS(ROOT, ("eppm",))
        super().run()


class CheckedSource(sdist):
    """Include verified embedded assets and their canonical browser source."""

    def run(self) -> None:
        """Validate embedded assets before source-distribution assembly."""
        CHECK_ASSETS(ROOT, ("eppm",))
        super().run()


class CheckedEditable(editable_wheel):
    """Fail development installs when required resources are unprepared."""

    def run(self) -> None:
        """Validate embedded assets before editable installation."""
        CHECK_ASSETS(ROOT, ("eppm",))
        super().run()


setup(cmdclass={
    "build_py": CheckedBuild, "sdist": CheckedSource,
    "editable_wheel": CheckedEditable,
})
