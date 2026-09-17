"""Reusable cascading organization buttons with page-owned filter state."""

from collections.abc import Callable

import streamlit as st

from app.domain.organization.project_filters import ORGANIZATION_FACETS
from app.presentation.i18n import t


def organization_filter_panel(
    choices: Callable[[dict[str, list[str]], str], list[str]],
    labels: dict[str, dict[str, str]],
    *, prefix: str,
    on_change: Callable[[], None],
) -> dict[str, list[str]]:
    """Render services above compact, initially collapsed organization frames.

    Choices depend only on upstream organization facets. Other page filters
    cannot hide service buttons. Native multiselect pills toggle independently
    for ordinary clicks, Ctrl-clicks, and keyboard activation.
    """
    active: dict[str, list[str]] = {}
    titles = {
        'service': t('organization_filters.services', default='Services'),
        'division': t('organization_filters.divisions', default='Divisions'),
        'org_team': t('organization_filters.teams', default='Teams'),
        'org_manager': t('organization_filters.managers', default='Project managers'),
    }
    st.html("""
        <style>
        .st-key-organization_filter_frames[data-testid="stVerticalBlock"] {
            gap: 0.5rem;
        }
        .st-key-organization_filter_frames details:not([open]) > summary {
            height: 22px;
            min-height: 22px;
            padding-block: 0;
        }
        </style>
    """)
    with st.container(key='organization_filter_frames'):
        for facet in ORGANIZATION_FACETS:
            title = titles[facet]
            options = choices(active, facet)
            names = labels.get(facet, {})
            options = sorted(options, key=lambda value: (value == '', names.get(value, value).casefold(), value))
            key = prefix + facet
            previous = st.session_state.get(key, [])
            selected = [value for value in previous if value in options]
            if selected != previous:
                on_change()
            st.session_state[key] = selected
            frame = st.container(border=True) if facet == 'service' else st.expander(title, expanded=False)
            with frame:
                active[facet] = st.pills(
                    title, options, selection_mode='multi', key=key, label_visibility='collapsed',
                    format_func=lambda value, names=names: names.get(value, value) if value else
                        t('organization_filters.unassigned', default='Not assigned'),
                    on_change=on_change, width='stretch', wrap=True,
                )
    return active
