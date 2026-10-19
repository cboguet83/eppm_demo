"""Keyed Streamlit planning display with validated queued events."""

from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Protocol, cast

import streamlit as st
from streamlit.components.v1 import declare_component

from .contracts import (
    JsonObject,
    JsonValue,
    PlanningContractError,
    json_object,
    validate_event,
    validate_message,
)

__all__ = ["PlanningContractError", "planning_view"]
__version__ = "0.2.0"
_RECENT_EVENTS = 256


class _Component(Protocol):
    """Describe the injected Streamlit component invocation boundary."""

    def __call__(self, **kwargs: object) -> object: ...


@lru_cache(maxsize=1)
def _component() -> _Component:
    frontend = Path(__file__).with_name("frontend")
    if not (frontend / "index.html").is_file():
        raise RuntimeError(
            "Planning frontend assets are missing; "
            "prepare the distribution before use."
        )
    return cast(
        _Component, declare_component("planning_view", path=str(frontend)),
    )


def _state(key: str) -> JsonObject:
    namespace = "_planning_view_transport:" + key
    if namespace not in st.session_state:
        st.session_state[namespace] = {
            "acks": [], "pending": [], "scope": None, "revision": None,
        }
    return cast(JsonObject, st.session_state[namespace])


def _receive(key: str, value: object) -> None:
    if value is None:
        return
    event = validate_event(cast(JsonObject, value))
    state = _state(key)
    acknowledgements = cast(list[str], state["acks"])
    if event["requestId"] in acknowledgements:
        return
    acknowledgements.append(cast(str, event["requestId"]))
    del acknowledgements[:-_RECENT_EVENTS]
    if (event["scope"], event["revision"]) != (
        state["scope"], state["revision"],
    ):
        return
    cast(list[JsonValue], state["pending"]).append(event)


def planning_view(
    snapshot: Mapping[str, JsonValue],
    *,
    key: str,
    updates: Sequence[Mapping[str, JsonValue]] = (),
    options: Mapping[str, JsonValue] | None = None,
    lazy: bool = False,
) -> JsonObject | None:
    """Render one keyed display and return each validated intention once.

    Args:
        snapshot: Complete contract-v1 data; browser checks render fields.
        key: Explicit stable widget key, unique within the application.
        updates: Patches or correlated responses to deliver on this rerun.
        options: Mount configuration; labels/capabilities belong in data.
        lazy: Emit queued load events for a Python host to answer with patches.

    Returns:
        One validated event or None; hosts authorize and persist it.

    Raises:
        PlanningContractError: A key, JSON value, message, or event is invalid.
        RuntimeError: The installed package is missing its prepared frontend.
    """
    if not isinstance(key, str) or not key.strip():
        raise PlanningContractError("Invalid planning contract at key")
    if not isinstance(lazy, bool):
        raise PlanningContractError("Invalid planning contract at lazy")
    initial = validate_message(snapshot)
    if initial["kind"] != "snapshot":
        raise PlanningContractError("Invalid planning contract at snapshot")
    messages = [validate_message(message) for message in updates]
    configuration = json_object(options) if options is not None else {}
    state = _state(key)
    if (state["scope"], state["revision"]) != (
        initial["scope"], initial["revision"],
    ):
        state["pending"] = []
    state["scope"], state["revision"] = initial["scope"], initial["revision"]

    def receive() -> None:
        _receive(key, st.session_state.get(key))

    value = _component()(
        snapshot=initial, messages=messages, options=configuration, lazy=lazy,
        ackRequestIds=list(cast(list[str], state["acks"])), key=key,
        default=None, on_change=receive,
    )
    # Cover restored/replayed values that do not fire on_change. The bounded
    # acknowledgement set makes this idempotent.
    _receive(key, value)
    pending = cast(list[JsonValue], state["pending"])
    return cast(JsonObject, pending.pop(0)) if pending else None
