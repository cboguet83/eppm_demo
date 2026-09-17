"""Searchable checkbox dropdown for compact multi-value filters."""

from collections.abc import Callable

import streamlit as st

from app.presentation.i18n import t


def checkbox_filter(
    label: str, options: list[str], labels: dict[str, str], *, key: str,
    on_change: Callable[[], None],
) -> list[str]:
    """Filter immediately using checkboxes, search, select all, and clear.

    The canonical selection lives at ``key`` so external chart selections and
    page resets are reflected in the dropdown on its next render.
    """
    selected = [value for value in st.session_state.get(key, []) if value in options]
    st.session_state[key] = selected
    names = {value: labels.get(value, value) or t('dashboard.unassigned') for value in options}
    summary = ', '.join(names[value] for value in selected)
    if not selected:
        summary = t('checkbox_filter.all', default='All')
    elif len(selected) > 2:
        summary = t('checkbox_filter.selected', default='{count} selected', count=len(selected))

    def set_selection(values: list[str]) -> None:
        st.session_state[key] = values
        on_change()

    def toggle(value: str, widget_key: str) -> None:
        current = [item for item in st.session_state[key] if item != value]
        if st.session_state[widget_key]:
            current.append(value)
        set_selection([item for item in options if item in current])

    with st.container(key=key):
        with st.popover(f'{label}: {summary}', width='stretch', icon=':material/filter_alt:'):
            query = st.text_input(t('checkbox_filter.search', default='Search'), key=key + '_search')
            visible = [value for value in options if query.casefold() in names[value].casefold()]
            with st.container(horizontal=True):
                st.button(t('checkbox_filter.select_all', default='Select all'), key=key + '_all',
                          on_click=set_selection, args=(options,))
                st.button(t('checkbox_filter.clear', default='Clear'), key=key + '_clear',
                          on_click=set_selection, args=([],))
            with st.container(height=240, border=False):
                for value in visible:
                    widget_key = key + '_option_' + value
                    st.session_state[widget_key] = value in selected
                    st.checkbox(names[value], key=widget_key, on_change=toggle, args=(value, widget_key))
                if not visible:
                    st.caption(t('checkbox_filter.no_matches', default='No matching options'))
    return st.session_state[key]
