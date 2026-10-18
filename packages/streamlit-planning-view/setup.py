"""Reject incomplete standalone distributions before packaging."""

from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.editable_wheel import editable_wheel
from setuptools.command.sdist import sdist

from build_frontend import validate_frontend


class CheckedBuild(build_py):
    """Verify prepared resources before building package data."""

    def run(self) -> None:
        """Validate the complete local source and build its wheel tree."""
        validate_frontend(Path(__file__).resolve().parent)
        super().run()


class CheckedSource(sdist):
    """Keep the prepared frontend inside independently rebuildable sources."""

    def run(self) -> None:
        """Validate prepared assets before source-distribution assembly."""
        validate_frontend(Path(__file__).resolve().parent)
        super().run()


class CheckedEditable(editable_wheel):
    """Keep development installation subject to the same resource checks."""

    def run(self) -> None:
        """Validate prepared assets before editable wheel assembly."""
        validate_frontend(Path(__file__).resolve().parent)
        super().run()


setup(cmdclass={
    "build_py": CheckedBuild, "sdist": CheckedSource,
    "editable_wheel": CheckedEditable,
})
