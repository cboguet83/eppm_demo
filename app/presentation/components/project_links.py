"""Consistent property-row presentation and draft editing for custom web links."""

import html

import pandas as pd
import streamlit as st

from app.domain.projects.links import LinkValues, normalize_link
from app.presentation.i18n import t


def render_link_rows(links: list[LinkValues]) -> None:
    """Use the same alias/value columns and URL anchors as template link fields."""
    for link in links:
        clean = normalize_link(link["url"], link["alias"])
        url, alias = html.escape(clean["url"], quote=True), html.escape(clean["alias"])
        st.html(
            '<div style="display:grid;grid-template-columns:minmax(10rem,25%) minmax(0,1fr);'
            'column-gap:2rem;padding:.25rem 0;overflow-wrap:anywhere">'
            f'<span>{alias}:</span><span><a href="{url}" target="_blank" '
            f'rel="noopener noreferrer">{url}</a></span></div>'
        )


def render_links_editor(links: list[LinkValues], key: str, *, disabled: bool = False) -> list[LinkValues]:
    """Edit a draft collection saved atomically with the project, including creation."""
    st.subheader(t("project_collaboration.custom_links", default="Custom links"))
    if disabled:
        render_link_rows(links)
        return links
    edited = st.data_editor(
        pd.DataFrame(links, columns=["alias", "url"]), key=key, num_rows="dynamic",
        hide_index=True, width="stretch",
        column_config={
            "alias": st.column_config.TextColumn(t("project_collaboration.link_alias", default="Display alias"), required=True),
            "url": st.column_config.TextColumn("URL", required=True),
        },
    )
    return [LinkValues(alias=str(row["alias"] or ""), url=str(row["url"] or ""))
            for row in edited.fillna("").to_dict("records") if row["alias"] or row["url"]]
