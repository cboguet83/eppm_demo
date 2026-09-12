"""Settings editor for the shared hierarchy-type catalog and translations."""

import streamlit as st

from app.application.services.organization import OrganizationService
from app.domain.hierarchy import HierarchyType
from app.presentation.components.organization_dialogs import organization_errors, require_change
from app.presentation.i18n import SUPPORTED_LOCALES, get_current_locale, t


@organization_errors
def render_hierarchy_types(service: OrganizationService) -> None:
    """Manage classifications without changing their stable codes or assignments."""
    st.subheader(t("hierarchy.title"))
    st.caption(t("hierarchy.help"))
    records = service.get_all_hierarchy_types()
    by_id = {record.id: record for record in records}
    selected = st.selectbox(
        t("hierarchy.type"), [0, *by_id], key="hierarchy_catalog_selection",
        format_func=lambda value: by_id[value].label(get_current_locale()) if value else t("hierarchy.new"),
    )
    current = by_id.get(selected)
    with st.form(f"hierarchy_form_{selected}"):
        code = st.text_input(t("hierarchy.code"), value=current.code if current else "", disabled=current is not None)
        labels = {
            locale: st.text_input(
                language, value=current.translations.get(locale, "") if current else "", max_chars=120,
            )
            for locale, language in SUPPORTED_LOCALES.items()
        }
        if st.form_submit_button(t("hierarchy.save"), type="primary"):
            service.save_hierarchy_type(HierarchyType(
                code=code, id=selected or None, translations={locale: label for locale, label in labels.items() if label.strip()},
            ))
            st.toast(t("hierarchy.saved"))
            st.rerun()
    if current:
        confirmed = st.checkbox(t("hierarchy.delete_confirm"), key=f"hierarchy_delete_confirm_{selected}")
        if st.button(t("hierarchy.delete"), disabled=not confirmed):
            require_change(service.delete_hierarchy_type(selected))
            st.session_state.pop("hierarchy_catalog_selection", None)
            st.toast(t("hierarchy.deleted"))
            st.rerun()
