"""Preserve page position while lazy detail tabs change their content height."""

import streamlit as st


_POSITION_JS = """
export default function({data, parentElement}) {
    let node = parentElement, panel;
    while (node && !panel) {
        panel = node.closest?.('.st-key-' + data.panel_key);
        node = node.getRootNode?.().host;
    }
    if (!panel) return;
    const remember = event => {
        if (!event.target.closest('[role="tab"]')) return;
        // Reserve the existing height before a lazy tab removes its content.
        // This prevents browser scroll clamping at the bottom of the page.
        panel.style.minHeight = Math.max(panel.clientHeight, parseFloat(panel.style.minHeight) || 0) + 'px';
    };
    panel.addEventListener('pointerdown', remember, true);
    panel.addEventListener('keydown', remember, true);
    return () => {
        panel.removeEventListener('pointerdown', remember, true);
        panel.removeEventListener('keydown', remember, true);
    };
}
"""


def preserve_tab_position(panel_key: str) -> None:
    """Reserve the enclosing keyed panel's height before switching lazy tabs."""
    component = st.components.v2.component(
        "eppm_tab_position", html="<span></span>", js=_POSITION_JS,
    )
    component(data={"panel_key": panel_key}, key=panel_key + "_position", height=0)
