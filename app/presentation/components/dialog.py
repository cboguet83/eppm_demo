"""Reveal native dialogs together after their initial content has mounted."""

from collections.abc import Callable
from functools import wraps
from typing import Literal

import streamlit as st


_CSS = """
<style>
[data-testid="stDialog"] [role="dialog"]:not([data-eppm-ready]) {
    visibility: hidden;
}
body:has([data-testid="stApp"][data-test-script-state="notRunning"])
    [data-testid="stDialog"] [role="dialog"]:has([data-testid="stAlert"]),
body:has([data-testid="stApp"][data-test-script-state="notRunning"])
    [data-testid="stDialog"] [role="dialog"]:has([data-testid="stException"]) {
    visibility: visible;
}
.st-key-eppm_dialog_ready {height: 0; min-height: 0; margin: 0;}
</style>
"""

_READY_JS = """
export default function({parentElement}) {
    let node = parentElement, dialog;
    while (node && !dialog) {
        dialog = node.closest?.('[role="dialog"]');
        node = node.getRootNode?.().host;
    }
    if (!dialog || dialog.hasAttribute('data-eppm-ready')) return;
    let frame = 0, disposed = false;
    const pending = () => dialog.querySelector(
        '[data-testid="stSkeleton"], [data-testid="stElementPlaceholder"]');
    const reveal = () => {
        if (disposed || !dialog.isConnected || pending()) return;
        dialog.setAttribute('data-eppm-ready', 'true');
        observer.disconnect();
        const focus = dialog.querySelector(
            'input:not(:disabled), textarea:not(:disabled), select:not(:disabled)')
            || dialog.querySelector('button:not(:disabled)');
        focus?.focus({preventScroll: true});
    };
    const schedule = () => {
        cancelAnimationFrame(frame);
        // Wait for a layout/paint boundary, not an arbitrary loading timeout.
        frame = requestAnimationFrame(() => {frame = requestAnimationFrame(reveal);});
    };
    const observer = new MutationObserver(schedule);
    observer.observe(dialog, {childList: true, subtree: true});
    schedule();
    return () => {disposed = true; observer.disconnect(); cancelAnimationFrame(frame);};
}
"""


def install_dialog_presentation() -> None:
    """Load popup visibility rules with the shell, before any popup can open."""
    st.markdown(_CSS, unsafe_allow_html=True)


def dialog[**P](
    title: str, *, width: Literal["small", "medium", "large"] = "small",
    dismissible: bool = True, icon: str | None = None,
    on_dismiss: Literal["ignore", "rerun"] | Callable[[], None] = "ignore",
) -> Callable[[Callable[P, None]], Callable[P, None]]:
    """Keep native widgets, dismissal and fragment semantics without partial opening.

    The completion component is emitted after every initial body element, including
    handled errors and early returns. A stopped error render is revealed when the
    script finishes, since Streamlit rejects further output after st.stop().
    Subsequent updates keep the mounted dialog
    visible. This changes presentation only; reads and writes remain authorized by
    the existing services.
    """
    def decorate(render: Callable[P, None]) -> Callable[P, None]:
        @st.dialog(title, width=width, dismissible=dismissible, icon=icon, on_dismiss=on_dismiss)
        @wraps(render)
        def complete(*args: P.args, **kwargs: P.kwargs) -> None:
            try:
                render(*args, **kwargs)
            finally:
                ready = st.components.v2.component(
                    "eppm_dialog_ready", html="<span></span>", js=_READY_JS,
                )
                ready(key="eppm_dialog_ready", height=0)

        @wraps(render)
        def open_dialog(*args: P.args, **kwargs: P.kwargs) -> None:
            # Install before the portal is created, including standalone page tests.
            install_dialog_presentation()
            complete(*args, **kwargs)

        return open_dialog

    return decorate
