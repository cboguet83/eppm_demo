"""Dynamic property widgets shared by project forms and template defaults.

Values are deliberately dynamic at this UI boundary; the domain validates them
before persistence. Widget keys and draft handling retain their existing behavior.
"""

import datetime
from typing import Any, Optional

import pandas as pd
import streamlit as st


def render_dynamic_field(
    parameter: pd.Series,
    options: pd.DataFrame,
    current_value: Any,
    key_prefix: str,
) -> Any:
    """Render the input matching one dynamic project-parameter type."""
    param_id = str(parameter["param_id"])
    param_name = str(parameter["param_name"])
    param_type = str(parameter["param_type"]).upper()
    mandatory = bool(parameter.get("mandatory", False))
    alias = (
        str(parameter.get("alias", "")).strip()
        if pd.notna(parameter.get("alias"))
        else ""
    )
    label = f"{alias or param_name}{' *' if mandatory else ''}"
    key = f"{key_prefix}_{param_id}"
    draft_key = f"{key_prefix}_draft"
    is_creation = key_prefix.startswith("portfolio_create_")

    def remember_edit() -> None:
        draft = dict(st.session_state.get(draft_key, {}))
        draft[param_id] = st.session_state[key]
        st.session_state[draft_key] = draft

    if is_creation:
        draft = st.session_state.get(draft_key, {})
        if param_id in draft:
            current_value = draft[param_id]
        else:
            # Untouched fields follow the newly selected type's creation default.
            st.session_state.pop(key, None)
    widget_args = {"key": key, "persist_state": "page", "on_change": remember_edit if is_creation else None}

    if param_type == "TEXT":
        return st.text_input(
            label,
            value=str(current_value) if current_value is not None else "",
            **widget_args,
        )
    if param_type in ("URL", "HYPERLINK"):
        return st.text_input(
            label,
            value=str(current_value) if current_value is not None else "",
            placeholder="https://...",
            **widget_args,
        )
    if param_type == "DATE":
        parsed_date: Optional[datetime.date] = None
        if isinstance(current_value, datetime.date):
            parsed_date = current_value
        if current_value and isinstance(current_value, str):
            try:
                parsed_date = datetime.date.fromisoformat(current_value.strip())
            except ValueError:
                parsed_date = None
        selected_date = st.date_input(label, value=parsed_date, **widget_args)
        return selected_date.isoformat() if selected_date is not None else ""
    if param_type == "NUMBER":
        number_value: Optional[float] = None
        if current_value is not None and str(current_value).strip():
            try:
                number_value = float(current_value)
            except (TypeError, ValueError):
                number_value = None
        return st.number_input(label, value=number_value, **widget_args)
    if param_type == "ENUM":
        param_options = (
            options[options["param_id"] == param_id]["option_value"].tolist()
            if not options.empty
            else []
        )
        choices = [""] + param_options
        current_index = choices.index(current_value) if current_value in choices else 0
        return st.selectbox(label, options=choices, index=current_index, **widget_args)
    if param_type in ("MULTI_ENUM", "TAGS"):
        param_options = (
            options[options["param_id"] == param_id]["option_value"].tolist()
            if not options.empty
            else []
        )
        current_values = (
            current_value
            if isinstance(current_value, list)
            else ([current_value] if current_value else [])
        )
        choices = sorted(set(param_options + current_values))
        return st.multiselect(
            f"{label} ({param_type})",
            options=choices,
            default=[value for value in current_values if value in choices],
            accept_new_options=param_type == "TAGS",
            **widget_args,
        )
    return st.text_input(
        label,
        value=str(current_value) if current_value is not None else "",
        **widget_args,
    )
