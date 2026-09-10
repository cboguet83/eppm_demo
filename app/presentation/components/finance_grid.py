"""Local editable finance grid; only explicit save/import/navigation reaches Python."""

from collections.abc import Callable
from importlib.resources import files

import streamlit as st


def finance_grid(data: dict[str, object], on_action: Callable[[], None]) -> None:
    """Mount the split grid with a validated JSON display model and action callback."""
    assets = files("app").joinpath("presentation", "assets")
    component = st.components.v2.component(
        "eppm_finance_grid", html='<section class="finance"></section>',
        js=assets.joinpath("finance_grid.js").read_text(encoding="utf-8"),
        css=assets.joinpath("finance_grid.css").read_text(encoding="utf-8"),
    )
    component(data=data, key="finance_grid", height="content", on_action_change=on_action)
