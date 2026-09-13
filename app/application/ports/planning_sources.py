"""Opaque source fingerprints for consistent, bounded task display reads."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PlanningDisplaySources:
    """Chart revision and task fingerprints captured in the same read snapshot."""

    revision: tuple
    tokens: dict[int, str]


class PlanningSourceReader(Protocol):
    """Reauthorize source reads; fingerprints never grant access to task data."""

    def capture(self, project_ids: list[int]) -> PlanningDisplaySources:
        """Capture sources before constructing the corresponding chart data."""
        ...

    def read(self, project_ids: list[int]) -> dict[int, str]:
        """Read current fingerprints for one bounded batch and its assigned pools."""
        ...
