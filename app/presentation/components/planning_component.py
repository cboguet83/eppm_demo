"""Adapt EPPM's dynamic presentation DTOs to the shared browser transport.

The browser adapter translates these existing application DTOs into the public
planning contract. ``Any`` is limited to Streamlit's dynamic JSON/widget boundary.
"""

from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from app.presentation.assets import component_path


def render_planning_component(**payload: Any) -> dict[str, Any] | None:
    """Render and acknowledge one keyed EPPM component without changing its API.

    Args:
        **payload: Application-owned planning data and Streamlit widget options.

    Returns:
        The established application event dictionary, or no event before input.
    """
    event = st.session_state.get(payload["key"])
    if isinstance(event, dict) and isinstance(event.get("nonce"), str):
        payload["ack_nonce"] = event["nonce"]
    component = components.declare_component(
        "interactive_gantt", path=str(component_path("gantt"))
    )
    return component(**payload)
