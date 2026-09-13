"""Bounded thread-stack sampling for explicitly profiled browser pilots.

Only code locations are retained, never frame locals, arguments or source text.
Counts are diagnostic wall-time samples, not deterministic function timings.
"""

from collections import Counter
import json
from pathlib import Path
import sys
import threading
from time import monotonic
from typing import NamedTuple


class Location(NamedTuple):
    """A code location without application data from the frame."""

    file: str
    function: str
    line: int


class StackProfiler:
    """Sample active application stacks without owning Python's profiling hook."""

    def __init__(self, path: Path, *, source_prefix: str = "/app/app/",
                 interval: float = 0.02, max_stacks: int = 10000) -> None:
        self.path = path
        self.source_prefix = source_prefix.replace("\\", "/")
        self.interval = interval
        self.max_stacks = max_stacks
        self.stacks: Counter[tuple[Location, ...]] = Counter()
        self.cycles = 0
        self.dropped = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._collect, name="benchmark-profiles", daemon=True)

    def sample(self) -> None:
        """Capture bounded code-only stacks from other application threads."""
        self.cycles += 1
        for identity, frame in sys._current_frames().items():
            if identity == threading.get_ident():
                continue
            stack = []
            while frame is not None and len(stack) < 128:
                code = frame.f_code
                stack.append(Location(code.co_filename.replace("\\", "/"), code.co_name, frame.f_lineno))
                frame = frame.f_back
            if not any(location.file.startswith(self.source_prefix) for location in stack):
                continue
            key = tuple(reversed(stack))
            if key in self.stacks or len(self.stacks) < self.max_stacks:
                self.stacks[key] += 1
            else:
                self.dropped += 1

    def write(self) -> None:
        """Persist diagnostic counts, including any discarded stack samples."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "kind": "thread_stack_samples", "interval_seconds": self.interval,
            "cycles": self.cycles, "dropped_samples": self.dropped,
            "stacks": [{"count": count, "locations": [location._asdict() for location in stack]}
                       for stack, count in self.stacks.most_common()],
        }), encoding="utf-8")

    def start(self) -> None:
        """Start the independent sampler thread."""
        self._thread.start()

    def stop(self) -> None:
        """Stop sampling and retain the final observations."""
        self._stop.set()
        self._thread.join()

    def _collect(self) -> None:
        next_write = monotonic() + 2
        try:
            while not self._stop.wait(self.interval):
                self.sample()
                if monotonic() >= next_write:
                    self.write()
                    next_write = monotonic() + 2
        finally:
            self.write()
