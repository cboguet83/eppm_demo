"""Clean installed-artifact interpreters without checkout editable import hooks."""

import os
from pathlib import Path
import subprocess
import sysconfig
import venv


def isolated_installed_runtime(
    directory: Path, installed: Path,
) -> tuple[Path, dict[str, str]]:
    """Provide third-party dependencies in a fresh, non-editable interpreter.

    Args:
        directory: Private artifact-consumer directory owned by this test.
        installed: Directory containing only the wheel being exercised.

    Returns:
        Interpreter path and environment for installed-artifact probes/servers.

    Raises:
        OSError: An owned interpreter or dependency link cannot be created.
        subprocess.CalledProcessError: A checkout package remains importable.
        subprocess.TimeoutExpired: Interpreter isolation cannot be verified.
    """
    environment_root = directory / 'runtime'
    venv.EnvBuilder(with_pip=False).create(environment_root)
    dependencies = Path(sysconfig.get_path('purelib', vars={
        'base': str(environment_root), 'platbase': str(environment_root),
    }))
    dependencies.mkdir(parents=True, exist_ok=True)
    for entry in Path(sysconfig.get_path('purelib')).iterdir():
        if (entry.name.startswith(('.', '__editable__', 'eppm_demo',
                                   'streamlit_planning_view'))
                or entry.name in {'app', 'scripts', 'tests', '__pycache__'}
                or entry.suffix in {'.pth', '.egg-link'}):
            continue
        (dependencies / entry.name).symlink_to(
            entry, target_is_directory=entry.is_dir(),
        )
    environment = os.environ.copy()
    environment['PYTHONPATH'] = str(installed)
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    python = environment_root / (
        'Scripts/python.exe' if os.name == 'nt' else 'bin/python'
    )
    subprocess.run([
        str(python), '-I', '-c',
        "import importlib.util;"
        "assert importlib.util.find_spec('app') is None;"
        "assert importlib.util.find_spec('scripts') is None;"
        "assert importlib.util.find_spec('streamlit_planning_view') is None",
    ], cwd=directory, env=environment, capture_output=True, text=True,
        timeout=15, check=True)
    return python, environment
