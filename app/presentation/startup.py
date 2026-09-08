"""Streamlit startup caching with explicit database identity and migration version."""

import streamlit as st

from app.application.services.maintenance import MaintenanceService


@st.cache_resource
def bootstrap_database(
    database_identity: str,
    schema_version: str,
    force: bool,
    projects: int,
    _service: MaintenanceService,
) -> bool:
    """Run startup once per explicit source/version/options cache key.

    The service is injected and excluded from Streamlit hashing. Normal display
    cache invalidation must not clear this resource and repeat forced startup.
    """
    _service.startup(force=force, projects=projects)
    return True
