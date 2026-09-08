"""Screen 5: Organization Structure & Settings Management View with Contextual Menus and Dialogs."""

import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import pandas as pd
import streamlit as st

from src.i18n import t
from src.models.constants import PAGE_PLANNING
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.resource_pool_repo import ResourcePoolRepository
from src.repositories.schema_repo import SchemaRepository
from src.repositories.tag_repo import TagRepository
from app.main import (
    create_schema_service,
    create_project_type_service,
    create_organization_service,
    create_resource_pool_service,
    create_pool_capacity_service,
    create_tag_service,
    create_collaboration_service,
)
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


def render_settings_view(
    org_repo: OrganizationRepository,
    tag_repo: Optional[TagRepository] = None,
    project_repo: Optional[ProjectRepository] = None,
    milestone_repo: Optional[MilestoneRepository] = None,
    pool_repo: Optional[ResourcePoolRepository] = None,
    schema_repo: Optional[SchemaRepository] = None,
) -> None:
    """Renders the Settings screen with sections for Organization Structure and Parameter Definition."""
    st.header(f"⚙️ {t('settings.title', default='Settings')}")
    schema_repo = schema_repo or SchemaRepository(org_repo.db_path)
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
            create_schema_service(schema_repo.db_path),
            create_project_type_service(schema_repo.db_path),
        )
        return
    if selected_section == "project_configuration":
        from app.presentation.pages.collaboration import render_project_catalog

        roles_tab, events_tab = st.tabs(
            [
                t("project_collaboration.roles", default="Project roles"),
                t("project_collaboration.types", default="Event types"),
            ],
            key="project_configuration_tab",
            on_change="rerun",
        )
        if roles_tab.open:
            with roles_tab:
                render_project_catalog(create_collaboration_service(org_repo.db_path), "role")
        if events_tab.open:
            with events_tab:
                render_project_catalog(create_collaboration_service(org_repo.db_path), "event_type")
        return
    tag_repo = tag_repo or TagRepository(org_repo.db_path)
    project_repo = project_repo or ProjectRepository(org_repo.db_path)
    milestone_repo = milestone_repo or MilestoneRepository(org_repo.db_path)
    pool_repo = pool_repo or ResourcePoolRepository(org_repo.db_path)
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
            render_functions(create_organization_service(org_repo.db_path))
    if tab_types.open:
        with tab_types:
            render_function_types(create_organization_service(org_repo.db_path))
    if tab_teams.open:
        with tab_teams:
            render_teams(create_organization_service(org_repo.db_path))
    if tab_emps.open:
        with tab_emps:
            render_employees(create_organization_service(org_repo.db_path))
    if tab_tag_groups.open:
        with tab_tag_groups:
            render_tag_groups(create_tag_service(tag_repo.db_path))
    if tab_tag_dict.open:
        with tab_tag_dict:
            render_tag_dictionary(create_tag_service(tag_repo.db_path))
    if tab_proj_tags.open:
        with tab_proj_tags:
            render_project_tags(create_tag_service(tag_repo.db_path))
    if tab_task_tags.open:
        with tab_task_tags:
            render_task_tags(create_tag_service(tag_repo.db_path))
    if tab_pools.open:
        with tab_pools:
            render_resource_pools(
                create_resource_pool_service(pool_repo.db_path),
                create_pool_capacity_service(pool_repo.db_path),
                create_organization_service(org_repo.db_path),
                PAGE_PLANNING,
            )
