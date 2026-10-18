"""Bounded observations of native Streamlit script completion in browser tests."""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

if TYPE_CHECKING:
    from playwright.sync_api import Page, WebSocket


class ScriptCompletion:
    """Observe actual completion messages without changing the served application.

    Attach before navigation so the initial successful run is observed. Rendered
    components can become visible before their enclosing script has finished.
    """

    def __init__(self, page: 'Page') -> None:
        """Attach protocol observers to the private browser page.

        Args:
            page: Native test page that has not navigated to its server yet.
        """
        self._page: Page = page
        self._completed: int = 0
        self._running: bool = False
        page.on('websocket', self._observe_socket)

    def _observe_socket(self, socket: 'WebSocket') -> None:
        socket.on('framereceived', self._receive)

    def _receive(self, payload: str | bytes) -> None:
        if not isinstance(payload, bytes):
            return
        message = ForwardMsg.FromString(payload)
        if message.HasField('session_status_changed'):
            self._running = message.session_status_changed.script_is_running
        if message.HasField('script_finished') and message.script_finished in {
            ForwardMsg.FINISHED_SUCCESSFULLY,
            ForwardMsg.FINISHED_FRAGMENT_RUN_SUCCESSFULLY,
        }:
            self._completed += 1

    def _until(self, predicate: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 10
        while not predicate():
            if time.monotonic() >= deadline:
                raise AssertionError('Streamlit script did not complete in 10 seconds')
            # Pump Playwright's synchronous event loop while awaiting the server.
            self._page.wait_for_timeout(10)

    @contextmanager
    def action(self) -> Iterator[None]:
        """Wait for the previous run and a new completion around one action.

        Yields:
            Control to perform one action that triggers a server rerun.

        Raises:
            AssertionError: The previous or requested run never completes.
        """
        self._until(lambda: self._completed > 0 and not self._running)
        previous = self._completed
        yield
        self._until(lambda: self._completed > previous and not self._running)
