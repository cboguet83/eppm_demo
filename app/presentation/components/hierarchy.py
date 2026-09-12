"""Optional hierarchy-type selector shared by organization and pool dialogs."""

import streamlit as st

from app.domain.hierarchy import HierarchyType
from app.presentation.i18n import get_current_locale, t


def hierarchy_type_selector(records: list[HierarchyType], selected: int | None = None) -> int | None:
    """Offer an explicit unassigned choice and preserve the current selection."""
    labels = {record.id: record.label(get_current_locale()) for record in records if record.id is not None}
    unassigned_label = t("hierarchy.none")
    # Use a concrete option value: None is also Streamlit's empty widget state.
    options = [0, *labels]
    value = st.selectbox(
        t("hierarchy.field"), options,
        index=options.index(selected) if selected in options else 0,
        format_func=lambda value: labels[value] if value else unassigned_label,
        key="hierarchy_type_selection",
    )
    return value or None
