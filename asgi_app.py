"""OIDC-enabled ASGI launcher: streamlit run asgi_app.py."""

import os
from pathlib import Path
from secrets import token_urlsafe
from time import time

from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
import streamlit as st

from app.infrastructure.authentication.http import AuthenticationRoutes, OIDC_COOKIE
from app.infrastructure.authentication.middleware import BrowserSecurityMiddleware
from app.infrastructure.authentication.oidc import create_oidc_client
from app.security import create_access_service
from app.shared.config import config
from app.shared.config.authentication import AuthenticationConfig
from app.shared.logging import get_logger, setup_logging


def script_error(error: Exception) -> bool:
    """Suppress internal exception details in browser-rendered scripts and callbacks."""
    reference = token_urlsafe(16)
    get_logger(__name__).error("application.operation_failed reference=%s", reference)
    st.error(f"The operation could not complete. Reference: {reference}")
    return True


def create_application() -> st.App:
    """Fail closed on missing configuration and compose supported Streamlit ASGI routes."""
    setup_logging()
    settings = AuthenticationConfig.from_environment(os.environ)
    access = create_access_service(config.db_path, settings)
    client = create_oidc_client(settings, config.db_path, lambda: int(time()))
    return st.App(
        Path(__file__).with_name("streamlit_app.py"),
        routes=AuthenticationRoutes(client, access).routes(),
        middleware=[Middleware(BrowserSecurityMiddleware, config=settings),
                    Middleware(SessionMiddleware, secret_key=settings.cookie_secret,
                               session_cookie=OIDC_COOKIE, max_age=600, same_site="lax",
                               https_only=settings.secure_cookies)],
        on_script_error=script_error,
    )


app = create_application()
