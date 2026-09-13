"""AppTest composition using real native resources without embedding credentials."""

from streamlit.testing.v1 import AppTest
import psycopg
import pytest

from app.application.services.business_access import BusinessAccess
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.runtime import RuntimeResources


def native_screen(source: str, resources: RuntimeResources, access: BusinessAccess) -> AppTest:
    """Bind native resources to trusted test source before its first script run."""
    app = AppTest.from_string('''
import streamlit as st
runtime = st.session_state['_test_native_resources']
access = st.session_state['_test_native_access']
''' + source, default_timeout=15)
    app.session_state['_test_native_resources'] = resources
    app.session_state['_test_native_access'] = access
    return app


@pytest.fixture
def runtime(authorized) -> RuntimeResources:
    """Install only editable reference choices through separate test setup."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        ensure_reference_catalog(connection)
    return RuntimeResources(authorized.database, authorized.key)


@pytest.fixture
def access(authorized) -> BusinessAccess:
    """Use a real native business-admin session for Settings workflows."""
    return authorized.binding(4).access
