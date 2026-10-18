"""Retain bounded, private startup failures after migrating the benchmark driver."""

import os
from pathlib import Path
import subprocess
import sys
import time


def test_mounted_benchmark_reports_early_exit_without_child_output(
    tmp_path: Path,
) -> None:
    """A failing executable must exit promptly without exposing startup output."""
    executable = tmp_path / "browser"
    with executable.open("w", encoding="utf-8") as stream:
        stream.write(
            f"#!{sys.executable}\nimport sys\n"
            "sys.stderr.write('No usable sandbox! private-startup-marker\\n')\n"
            "sys.exit(23)\n"
        )
    executable.chmod(0o700)

    started = time.monotonic()
    result = subprocess.run(
        ["node", "scripts/benchmark_gantt.cjs", str(executable)],
        env=os.environ | {"EPPM_BENCHMARK_PYTHON": sys.executable},
        capture_output=True, text=True, timeout=10, check=False,
    )

    assert result.returncode == 1
    assert time.monotonic() - started < 10
    assert "diagnostics=sandbox" in result.stderr
    assert "private-startup-marker" not in result.stderr
    assert str(executable) not in result.stderr
