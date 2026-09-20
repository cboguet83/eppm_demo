"""Reusable cascading organization buttons with page-owned filter state."""

from collections.abc import Callable

import streamlit as st

from app.domain.organization.project_filters import ORGANIZATION_FACETS
from app.presentation.i18n import t


_BUTTONS_JS = """
export default function({data, parentElement, setTriggerValue}) {
    const root = parentElement.querySelector('.organization-buttons');
    root.setAttribute('aria-label', data.title);
    root.replaceChildren();
    for (const option of data.options) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = option.label;
        button.title = data.hint;
        button.setAttribute('aria-description', data.hint);
        button.setAttribute('aria-pressed', String(data.selected.includes(option.value)));
        button.onclick = event => setTriggerValue('selection', {
            value: option.value, multiple: event.ctrlKey || event.metaKey,
        });
        root.appendChild(button);
    }
}
"""

_BUTTONS_CSS = """
.organization-buttons {display:flex;flex-wrap:wrap;gap:4px;}
button {flex:1 1 auto;min-height:32px;padding:4px 12px;border-radius:999px;
    border:1px solid var(--st-border-color);background:var(--st-background-color);
    color:var(--st-text-color);font:inherit;font-size:14px;cursor:pointer;}
button[aria-pressed="true"] {background:var(--st-primary-color);color:white;
    border-color:var(--st-primary-color);}
button:hover {border-color:var(--st-primary-color);}
button:focus-visible {outline:2px solid var(--st-primary-color);outline-offset:2px;}
"""


def _buttons(title: str, options: list[str], names: dict[str, str], key: str,
             on_change: Callable[[], None]) -> list[str]:
    """Render modifier-aware buttons and validate selections before filtering."""
    component_key = key + '_buttons'

    def select() -> None:
        event = getattr(st.session_state.get(component_key), 'selection', None)
        if not isinstance(event, dict) or event.get('value') not in options:
            return
        value = event['value']
        previous = st.session_state.get(key, [])
        if event.get('multiple') is True:
            selected = [item for item in previous if item != value] if value in previous else [*previous, value]
        else:
            selected = [] if previous == [value] else [value]
        st.session_state[key] = selected
        on_change()

    component = st.components.v2.component(
        'eppm_organization_buttons', html='<div class="organization-buttons" role="group"></div>',
        css=_BUTTONS_CSS, js=_BUTTONS_JS,
    )
    component(data={
        'title': title, 'selected': st.session_state[key],
        'hint': t('organization_filters.multiselect_hint', default='Ctrl+click to select multiple options.'),
        'options': [{'value': value, 'label': names.get(value, value) if value else
                     t('organization_filters.unassigned', default='Not assigned')} for value in options],
    }, key=component_key, width='stretch', height='content', on_selection_change=select)
    return st.session_state[key]


def organization_filter_panel(
    choices: Callable[[dict[str, list[str]], str], list[str]],
    labels: dict[str, dict[str, str]],
    *, prefix: str,
    on_change: Callable[[], None],
) -> dict[str, list[str]]:
    """Render services above compact, initially collapsed organization frames.

    Choices depend only on upstream organization facets. Other page filters
    cannot hide service buttons. Ordinary clicks replace the selection;
    Ctrl-clicks toggle individual options without clearing other selections.
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
        .st-key-organization_service_frame,
        .st-key-organization_filter_frames [data-testid="stExpanderDetails"] {
            padding: 2px;
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
            if facet == 'service':
                frame = st.container(border=True, key='organization_service_frame')
            else:
                frame_key = 'organization_frame_' + facet
                saved_key = 'organization_frame_state_' + facet
                if frame_key not in st.session_state:
                    st.session_state[frame_key] = st.session_state.get(saved_key, False)
                frame = st.expander(title, key=frame_key, on_change='rerun')
                st.session_state[saved_key] = frame.open
                if selected:
                    st.html(f'''<style>
                        .st-key-{frame_key} details:not([open]) > summary {{
                            background: #C41039; color: white;
                        }}
                    </style>''')
            with frame:
                active[facet] = _buttons(title, options, names, key, on_change)
    return active
