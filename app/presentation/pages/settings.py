"""Lazy Settings navigation using injected application services."""

import streamlit as st

from app.presentation.i18n import t
from app.presentation.navigation import PAGE_PLANNING
from app.presentation.components.settings_workspace import SettingsWorkspace
from app.presentation.pages.resource_pools import render_resource_pools
from app.presentation.pages.organization import (
    render_functions,
    render_function_types,
    render_teams,
    render_employees,
)
from app.presentation.pages.schema import render_schema_definition
from app.presentation.pages.tags import (
    render_tag_groups,
    render_tag_dictionary,
    render_project_tags,
    render_task_tags,
)


@st.fragment
def render_settings_view(workspace: SettingsWorkspace) -> None:
    """Switch Settings sections without rerunning navigation or portfolio totals."""
    st.header(f"⚙️ {t('settings.title', default='Settings')}")
    default_section_idx = 0
    if st.session_state.get("settings_active_section") == "parameters":
        default_section_idx = 1
    section_labels = {
        "org_structure": f"🏢 {t('settings.section_org_structure', default='Organization Structure')}",
        "param_def": f"🧩 {t('settings.section_param_definition', default='Parameter Definition')}",
        "project_configuration": t(
            "project_collaboration.configuration", default="Project configuration"
        ),
    }
    selected_section = st.radio(
        "Settings Section",
        options=list(section_labels),
        format_func=section_labels.get,
        index=default_section_idx,
        horizontal=True,
        label_visibility="collapsed",
        key="rb_settings_section",
    )
    if selected_section == "param_def":
        render_schema_definition(
            workspace.schema,
            workspace.types,
        )
        return
    if selected_section == "project_configuration":
        from app.presentation.pages.collaboration import render_project_catalog

        roles_tab, events_tab, wbs_tab = st.tabs(
            [
                t("project_collaboration.roles", default="Project roles"),
                t("project_collaboration.types", default="Event types"),
                t("wbs.title", default="WBS"),
            ],
            key="project_configuration_tab",
            on_change="rerun",
        )
        if roles_tab.open:
            with roles_tab:
                render_project_catalog(workspace.collaboration, "role")
        if events_tab.open:
            with events_tab:
                render_project_catalog(workspace.collaboration, "event_type")
        if wbs_tab.open:
            from app.presentation.pages.wbs import render_wbs_catalog
            with wbs_tab:
                render_wbs_catalog(workspace.wbs)
        return
    settings_tab_labels = [
        f"💼 {t('settings.tab_functions', default='Functions')}",
        f"🏷️ {t('settings.tab_types', default='Function Types')}",
        f"🛡️ {t('settings.tab_teams', default='Teams')}",
        f"👥 {t('settings.tab_employees', default='Employees')}",
        f"📁 {t('settings.tab_tag_groups', default='Tag Groups')}",
        f"📚 {t('settings.tab_tag_dict', default='Tag Dictionary')}",
        f"📌 {t('settings.tab_proj_tags', default='Project Tags')}",
        f"📋 {t('settings.tab_task_tags', default='Task Tags')}",
        f"🏊 {t('settings.tab_resource_pools', default='Resource Pools')}",
    ]
    requested_tab = st.session_state.pop("settings_active_tab", None)
    if requested_tab == "resource_pools":
        st.session_state["settings_tab_selection"] = settings_tab_labels[-1]
    (
        tab_funcs,
        tab_types,
        tab_teams,
        tab_emps,
        tab_tag_groups,
        tab_tag_dict,
        tab_proj_tags,
        tab_task_tags,
        tab_pools,
    ) = st.tabs(settings_tab_labels, key="settings_tab_selection", on_change="rerun")
    if tab_funcs.open:
        with tab_funcs:
            render_functions(workspace.organization)
    if tab_types.open:
        with tab_types:
            render_function_types(workspace.organization)
    if tab_teams.open:
        with tab_teams:
            render_teams(workspace.organization)
    if tab_emps.open:
        with tab_emps:
            render_employees(workspace.organization)
    if tab_tag_groups.open:
        with tab_tag_groups:
            render_tag_groups(workspace.tags)
    if tab_tag_dict.open:
        with tab_tag_dict:
            render_tag_dictionary(workspace.tags)
    if tab_proj_tags.open:
        with tab_proj_tags:
            render_project_tags(workspace.tags)
    if tab_task_tags.open:
        with tab_task_tags:
            render_task_tags(workspace.tags)
    if tab_pools.open:
        with tab_pools:
            render_resource_pools(
                workspace.resources,
                workspace.capacity,
                workspace.organization,
                PAGE_PLANNING,
            )
