"""AppTest composition using real native resources without embedding credentials."""

from streamlit.testing.v1 import AppTest

from app.application.services.business_access import BusinessAccess
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
