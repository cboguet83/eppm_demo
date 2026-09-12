"""Replayable use cases without driver, connection, or isolation-level types."""

from collections.abc import Callable
from typing import Protocol


class TransactionRunner[Store](Protocol):
    """Execute authorization, validation and persistence in a single snapshot.

    The callback can be replayed in full after a definite database rollback.
    It must preserve command inputs, and must not render UI, call external
    services, send messages, or otherwise perform effects outside its store.
    """

    def run[Result](
        self, operation: Callable[[Store], Result], *, write: bool = False,
    ) -> Result:
        """Return only after commit; bounded retries re-enter the entire callback."""
        ...
