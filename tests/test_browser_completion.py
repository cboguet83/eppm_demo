"""Regression checks for completion-aware native browser actions."""

from collections import deque
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

from tests.postgresql.browser_completion import ScriptCompletion


def _observer() -> tuple[ScriptCompletion, MagicMock, Callable[[str | bytes], None]]:
    page = MagicMock()
    completion = ScriptCompletion(page)
    socket = MagicMock()
    page.on.call_args.args[1](socket)
    assert page.on.call_args.args[0] == 'websocket'
    assert socket.on.call_args.args[0] == 'framereceived'
    return completion, page, socket.on.call_args.args[1]


def _running(value: bool) -> bytes:
    message = ForwardMsg()
    message.session_status_changed.script_is_running = value
    return message.SerializeToString()


def _finished(status: int) -> bytes:
    return ForwardMsg(script_finished=status).SerializeToString()


def test_action_waits_for_success_before_and_after_click() -> None:
    """A visible partial render or early rerun cannot authorize the next click."""
    completion, page, receive = _observer()
    events = deque([
        _running(True), _finished(ForwardMsg.FINISHED_EARLY_FOR_RERUN),
        _running(False), _running(True),
        _finished(ForwardMsg.FINISHED_SUCCESSFULLY), _running(False),
    ])
    page.wait_for_timeout.side_effect = lambda _: receive(events.popleft())

    with completion.action():
        assert not events
        events.extend([
            _running(True), _finished(ForwardMsg.FINISHED_EARLY_FOR_RERUN),
            _running(False), _running(True),
            _finished(ForwardMsg.FINISHED_FRAGMENT_RUN_SUCCESSFULLY),
            _running(False),
        ])

    assert not events
    assert page.wait_for_timeout.call_count == 12


@pytest.mark.parametrize('initial_completion', [False, True])
def test_action_fails_when_initial_or_requested_run_never_completes(
    monkeypatch: pytest.MonkeyPatch, initial_completion: bool,
) -> None:
    """Persistent missing acknowledgements fail instead of releasing an action."""
    completion, page, receive = _observer()
    if initial_completion:
        receive(_finished(ForwardMsg.FINISHED_SUCCESSFULLY))
    monkeypatch.setattr(
        'tests.postgresql.browser_completion.time.monotonic',
        MagicMock(side_effect=[0, 0, 11] if initial_completion else [0, 11]),
    )
    actions: list[str] = []

    with pytest.raises(AssertionError, match='did not complete'):
        with completion.action():
            actions.append('click')

    assert actions == (['click'] if initial_completion else [])
    page.wait_for_timeout.assert_not_called()


def test_action_preserves_failure_without_waiting_for_a_new_completion() -> None:
    """A failed browser action remains the reported error."""
    completion, page, receive = _observer()
    receive('unrelated text frame')
    receive(_finished(ForwardMsg.FINISHED_SUCCESSFULLY))

    with pytest.raises(ValueError, match='click failed'):
        with completion.action():
            raise ValueError('click failed')

    page.wait_for_timeout.assert_not_called()
