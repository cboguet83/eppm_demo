"""Launch the unchanged image application with explicit benchmark-only observers."""

import os
import runpy
import sys


def main() -> None:
    """Install observers only in the explicitly launched benchmark container."""
    from observer import install

    install(os.environ["LOAD_BACKEND"])
    sys.argv = ["streamlit", "run", "/app/asgi_app.py", "--server.fileWatcherType=none"]
    runpy.run_module("streamlit", run_name="__main__")


if __name__ == "__main__":
    main()
