"""Table and modal editors for shared hierarchy classifications."""

import streamlit as st

from app.application.services.organization import OrganizationService
from app.domain.hierarchy import HierarchyType
from app.presentation.components.dialog import dialog
from app.presentation.components.organization_dialogs import organization_errors, require_change
from app.presentation.i18n import SUPPORTED_LOCALES, get_current_locale, t
from app.presentation.pages.organization import _table


@organization_errors
def render_hierarchy_types(service: OrganizationService) -> None:
    """Show localized classifications using the shared type table and row actions."""
    st.subheader(t("hierarchy.title"))
    records = service.get_all_hierarchy_types()
    by_id = {record.id: record for record in records}
    # Reuse the Function Types component's event contract with hierarchy identities.
    event = _table(
        "function_type_table",
        types=[{"function_type_id": record.id,
                "function_type": record.label(get_current_locale())} for record in records],
        translations={
            "col_type_name": t("hierarchy.type"),
            "entity_name": t("hierarchy.type"),
            "stat_types": t("hierarchy.title"),
            "action_add": t("settings.action_add", default="Add New"),
            "action_edit": t("settings.action_edit", default="Edit"),
            "action_delete": t("settings.action_delete", default="Delete"),
            "filter_clear": t("settings.filter_clear", default="Clear Filters"),
            "filter_all": t("settings.filter_all", default="All"),
            "search_values": t("settings.search_values", default="Search values..."),
            "select_all": t("settings.select_all", default="Select All"),
            "clear": t("settings.clear", default="Clear"),
            "apply": t("settings.apply", default="Apply"),
            "btn_cancel": t("settings.btn_cancel", default="Cancel"),
            "selected_count": t("settings.selected_count", default="{count} selected"),
            "blanks": t("settings.blanks", default="(Blanks / None)"),
            "no_types": t("hierarchy.empty", default="No hierarchy types registered."),
        },
        key="hierarchy_interactive_table", default=None,
    )
    if not event or not event.get("nonce"):
        return
    if event["nonce"] == st.session_state.get("_last_hierarchy_table_nonce"):
        return
    st.session_state["_last_hierarchy_table_nonce"] = event["nonce"]
    action = event.get("action")
    if action == "add_function_type":
        _edit_hierarchy_type(service)
        return
    identifier = event.get("function_type_id")
    if type(identifier) is not int or identifier not in by_id:
        raise ValueError("This record no longer exists. Please refresh and try again.")
    current = by_id[identifier]
    if action == "edit_function_type":
        _edit_hierarchy_type(service, current)
    elif action == "delete_function_type":
        _delete_hierarchy_type(service, current)


@dialog(t("hierarchy.type"))
@organization_errors
def _edit_hierarchy_type(service: OrganizationService, current: HierarchyType | None = None) -> None:
    """Create or edit translated labels while keeping existing codes immutable."""
    st.caption(t("hierarchy.help"))
    with st.form("hierarchy_edit_form"):
        code = st.text_input(t("hierarchy.code"), value=current.code if current else "",
                             disabled=current is not None)
        labels = {
            locale: st.text_input(language,
                value=current.translations.get(locale, "") if current else "", max_chars=120)
            for locale, language in SUPPORTED_LOCALES.items()
        }
        if st.form_submit_button(t("hierarchy.save"), type="primary"):
            service.save_hierarchy_type(HierarchyType(
                code=code, id=current.id if current else None,
                translations={locale: label for locale, label in labels.items() if label.strip()},
            ))
            st.toast(t("hierarchy.saved"))
            st.rerun()
    if st.button(t("settings.btn_cancel", default="Cancel")):
        st.rerun()


@dialog(t("hierarchy.delete"))
@organization_errors
def _delete_hierarchy_type(service: OrganizationService, current: HierarchyType) -> None:
    """Confirm deletion and preserve service checks for classifications in use."""
    st.write(current.label(get_current_locale()))
    confirmed = st.checkbox(t("hierarchy.delete_confirm"))
    if st.button(t("hierarchy.delete"), disabled=not confirmed, type="primary"):
        require_change(service.delete_hierarchy_type(current.id))
        st.toast(t("hierarchy.deleted"))
        st.rerun()
    if st.button(t("settings.btn_cancel", default="Cancel")):
        st.rerun()
