"""Verify prepared planning resources before root package/source builds."""

from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.editable_wheel import editable_wheel
from setuptools.command.sdist import sdist

from scripts.build_planning_assets import check_assets


class CheckedBuild(build_py):
    """Prevent incomplete or stale assets in installed EPPM wheels."""

    def run(self) -> None:
        """Validate the canonical embedded assets before packaging."""
        check_assets(Path(__file__).resolve().parent, ("eppm",))
        super().run()


class CheckedSource(sdist):
    """Include verified embedded assets and their canonical browser source."""

    def run(self) -> None:
        """Validate embedded assets before source-distribution assembly."""
        check_assets(Path(__file__).resolve().parent, ("eppm",))
        super().run()


class CheckedEditable(editable_wheel):
    """Fail development installs when required resources are unprepared."""

    def run(self) -> None:
        """Validate embedded assets before editable installation."""
        check_assets(Path(__file__).resolve().parent, ("eppm",))
        super().run()


setup(cmdclass={
    "build_py": CheckedBuild, "sdist": CheckedSource,
    "editable_wheel": CheckedEditable,
})
