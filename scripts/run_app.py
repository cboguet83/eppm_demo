"""Start Streamlit with file-watching defaults for development, demo or production."""

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import sys


def resolve_file_watcher(values: Mapping[str, str]) -> str:
    """Resolve the watcher without changing authentication environment settings.

    Args:
        values: Deployment environment variables. No secret values are inspected.

    Returns:
        The Streamlit watcher backend, with ``none`` disabling source watching.

    Raises:
        ValueError: A run mode, inherited environment or watcher is unsupported.
    """
    mode = values.get("APP_RUN_MODE", "auto").strip().lower() or "auto"
    if mode not in {"auto", "development", "demo", "production"}:
        raise ValueError("APP_RUN_MODE must be auto, development, demo or production.")
    if mode == "auto":
        environment = values.get("APP_ENV", "production").strip().lower()
        if environment not in {"development", "staging", "production"}:
            raise ValueError("APP_ENV must be development, staging or production.")
        mode = "development" if environment == "development" else "production"
    override = values.get("APP_FILE_WATCHER_TYPE", "").strip().lower()
    if override and override not in {"auto", "none", "poll", "watchdog"}:
        raise ValueError("APP_FILE_WATCHER_TYPE must be empty, auto, none, poll or watchdog.")
    return override or ("auto" if mode == "development" else "none")


def build_streamlit_command(values: Mapping[str, str], arguments: Sequence[str] = ()) -> list[str]:
    """Build a shell-free CLI command; explicit Streamlit arguments remain available.

    Args:
        values: Deployment environment used to resolve watcher defaults.
        arguments: Additional operator-supplied Streamlit command-line options.

    Returns:
        An argument list launching the existing authenticated ASGI application.
    """
    watcher = resolve_file_watcher(values)
    application = Path(__file__).resolve().parents[1] / "asgi_app.py"
    return [sys.executable, "-m", "streamlit", "run", str(application),
            "--server.fileWatcherType=" + watcher, *arguments]


def run(argv: Sequence[str] | None = None) -> int:
    """Replace the launcher with Streamlit, returning a safe error if startup fails."""
    try:
        command = build_streamlit_command(os.environ, sys.argv[1:] if argv is None else argv)
    except ValueError as error:
        sys.stderr.write(str(error) + "\n")
        return 2
    try:
        os.execv(sys.executable, command)
    except OSError:
        sys.stderr.write("Unable to start Streamlit. Check the Python environment and installation.\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
