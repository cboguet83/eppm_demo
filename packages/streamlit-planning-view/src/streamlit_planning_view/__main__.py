"""Launch the installed fixture example using the current Streamlit runtime."""

from pathlib import Path
import os
import sys
from typing import Never


def main() -> Never:
    """Launch the packaged example with caller-supplied Streamlit CLI options.

    Raises:
        OSError: The current Python runtime cannot launch Streamlit.
    """
    os.execv(sys.executable, [
        sys.executable, "-m", "streamlit", "run",
        str(Path(__file__).with_name("example.py")), *sys.argv[1:],
    ])


if __name__ == "__main__":
    main()
