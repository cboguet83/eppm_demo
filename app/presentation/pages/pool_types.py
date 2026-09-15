"""Pool type table, optional ancestry, and required resource-pool selectors."""

from collections.abc import Callable
from functools import wraps

import streamlit as st

from app.application.exceptions import ResourcePoolStorageError
from app.application.services.resource_pools import ResourcePoolService
from app.domain.resources.pool_types import PoolType, normalize_pool_type
from app.presentation.components.dialog import dialog
from app.presentation.i18n import SUPPORTED_LOCALES, get_current_locale, t
from app.presentation.pages.organization import _table


def _pool_type_errors[**P](render: Callable[P, None]) -> Callable[P, None]:
    """Keep application validation and storage errors visible inside dialog reruns."""
    @wraps(render)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            render(*args, **kwargs)
        except (ValueError, ResourcePoolStorageError) as exc:
            st.error(str(exc))
    return guarded


def pool_type_selector(service: ResourcePoolService, *, key: str, current: int = 1) -> int:
    """Require a catalog selection, defaulting new resource pools to Human."""
    labels = {item.id: item.label(get_current_locale()) for item in service.get_all_pool_types()}
    if not labels:
        raise ValueError("Create a pool type before creating a resource pool.")
    identities = list(labels)
    return st.selectbox(t("pool_types.required", default="Pool type *"), identities,
                        index=identities.index(current) if current in labels else 0,
                        format_func=labels.get, key=key)


@_pool_type_errors
def render_pool_types(service: ResourcePoolService) -> None:
    """Render the shared type table with parent labels and contextual CRUD actions."""
    st.subheader(t("pool_types.title", default="Pool Types"))
    records = service.get_all_pool_types()
    by_id = {item.id: item for item in records}
    labels = {item.id: item.label(get_current_locale()) for item in records}
    event = _table("function_type_table", show_parent=True,
        types=[{"function_type_id": item.id, "function_type": labels[item.id],
                "parent_name": labels.get(item.parent_pool_type_id, "")} for item in records],
        translations={
            "col_type_name": t("pool_types.name", default="Name"),
            "col_parent": t("pool_types.parent", default="Parent pool type"),
            "entity_name": t("pool_types.type", default="Pool type"),
            "stat_types": t("pool_types.title", default="Pool Types"),
            "no_types": t("pool_types.empty", default="No pool types registered."),
            **{key: t("settings." + key, default=default) for key, default in {
                "action_add": "Add New", "action_edit": "Edit", "action_delete": "Delete",
                "filter_clear": "Clear Filters", "filter_all": "All", "select_all": "Select All",
                "clear": "Clear", "apply": "Apply", "btn_cancel": "Cancel",
                "selected_count": "{count} selected", "blanks": "(Blanks / None)",
            }.items()},
        }, key="pool_type_interactive_table", default=None)
    if not event or not event.get("nonce") or event["nonce"] == st.session_state.get("_last_pool_type_nonce"):
        return
    st.session_state["_last_pool_type_nonce"] = event["nonce"]
    if event.get("action") == "add_function_type":
        _edit_pool_type(service)
        return
    identity = event.get("function_type_id")
    if type(identity) is not int or identity not in by_id:
        raise ValueError("This pool type no longer exists.")
    if event.get("action") == "edit_function_type":
        _edit_pool_type(service, by_id[identity])
    elif event.get("action") == "delete_function_type":
        _delete_pool_type(service, by_id[identity])


@dialog(t("pool_types.type", default="Pool type"))
@_pool_type_errors
def _edit_pool_type(service: ResourcePoolService, current: PoolType | None = None) -> None:
    """Edit a type's name, optional parent, and translated display names."""
    records = service.get_all_pool_types()
    choices = {None: t("hierarchy.none", default="None")}
    for item in records:
        candidate = PoolType(current.name if current else "New", id=current.id if current else None,
                             parent_pool_type_id=item.id)
        try:
            normalize_pool_type(candidate, records)
        except ValueError:
            continue
        choices[item.id] = item.label(get_current_locale())
    with st.form("pool_type_edit"):
        name = st.text_input(t("pool_types.name", default="Name"), value=current.name if current else "", max_chars=120)
        parent = current.parent_pool_type_id if current else None
        identities = list(choices)
        parent = st.selectbox(t("pool_types.parent", default="Parent pool type"), identities,
                             index=identities.index(parent) if parent in choices else 0,
                             format_func=choices.get)
        with st.expander(t("pool_types.translations", default="Translated names")):
            translations = {locale: st.text_input(language,
                value=current.translations.get(locale, "") if current else "", max_chars=120)
                for locale, language in SUPPORTED_LOCALES.items() if locale != "en"}
        if st.form_submit_button(t("pool_types.save", default="Save pool type"), type="primary"):
            service.save_pool_type(PoolType(name, id=current.id if current else None,
                parent_pool_type_id=parent,
                translations={locale: label for locale, label in translations.items() if label.strip()}))
            st.rerun()
    if st.button(t("settings.btn_cancel", default="Cancel")):
        st.rerun()


@dialog(t("pool_types.delete", default="Delete pool type"))
@_pool_type_errors
def _delete_pool_type(service: ResourcePoolService, current: PoolType) -> None:
    """Confirm deletion while the database protects pools and dependent types."""
    st.write(current.label(get_current_locale()))
    st.caption(t("pool_types.delete_help", default="Types used by pools or child types cannot be deleted."))
    if st.button(t("pool_types.delete", default="Delete pool type"), type="primary"):
        if not service.delete_pool_type(current.id):
            raise ValueError("This pool type no longer exists.")
        st.rerun()
    if st.button(t("settings.btn_cancel", default="Cancel")):
        st.rerun()
