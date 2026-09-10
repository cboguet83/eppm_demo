"""Business-administrator WBS catalog maintenance in Settings."""

import pandas as pd
import streamlit as st

from app.application.exceptions import ProjectStorageError
from app.application.services.wbs import WbsService
from app.presentation.i18n import t


@st.fragment
def render_wbs_catalog(service: WbsService) -> None:
    """Load and edit only the active catalog section, with authorized callbacks."""
    try:
        if not service.can_manage():
            st.info(t("wbs.denied"))
            return
        _catalog(service)
    except (ValueError, ProjectStorageError) as error:
        st.error(str(error))


def _catalog(service: WbsService) -> None:
    rows = service.list_catalog()
    st.subheader(t("wbs.title"))
    if rows:
        st.dataframe(pd.DataFrame([{t("wbs.code"): row["code"], t("wbs.description"): row["description"],
                                   t("wbs.remaining"): row["available"]} for row in rows]),
                     hide_index=True, width="stretch")
    choices = {row["id"]: row for row in rows}
    identities = [None, *choices]
    current = st.session_state.get("wbs_catalog_selection")
    selected = st.selectbox(t("wbs.entry"), identities, key="wbs_catalog_selection",
                            index=identities.index(current) if current in identities else 0,
                            format_func=lambda value: choices[value]["code"] if value in choices else t("wbs.new"))
    item = choices.get(selected, {})
    prefix = f"wbs_catalog_{selected}"

    def change(deleting: bool = False) -> None:
        try:
            if deleting:
                service.delete(selected)
                st.session_state["wbs_catalog_selection"] = None
            else:
                code = st.session_state[prefix + "_code"].strip()
                if st.session_state[prefix + "_fictive"] and not code.startswith("#"):
                    code = "#" + code
                saved = service.save(code, st.session_state[prefix + "_description"], selected)
                st.session_state["wbs_catalog_selection"] = saved
            st.session_state.pop("wbs_catalog_error", None)
        except (ValueError, ProjectStorageError) as error:
            st.session_state["wbs_catalog_error"] = str(error)

    with st.form(prefix):
        st.text_input(t("wbs.code"), value=item.get("code", "").removeprefix("#"),
                      key=prefix + "_code", help=t("wbs.code_help"))
        st.checkbox(t("wbs.fictive"), value=item.get("code", "").startswith("#"), key=prefix + "_fictive")
        st.text_area(t("wbs.description"), value=item.get("description", ""), key=prefix + "_description")
        st.form_submit_button(t("wbs.save"), type="primary", on_click=change)
    if selected is not None:
        confirmed = st.checkbox(t("wbs.confirm_delete"), key=prefix + "_confirm")
        st.button(t("wbs.delete"), disabled=not confirmed, on_click=change, args=(True,))
    if error := st.session_state.pop("wbs_catalog_error", None):
        st.error(error)
