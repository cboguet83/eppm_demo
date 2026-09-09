"""OIDC-enabled ASGI launcher: streamlit run asgi_app.py."""

import os
from pathlib import Path
from secrets import token_urlsafe
from time import time

from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import BaseRoute
import streamlit as st

from app.infrastructure.authentication.http import AuthenticationRoutes, OIDC_COOKIE
from app.infrastructure.authentication.downloads import DownloadRoutes
from app.infrastructure.authentication.session_middleware import ApplicationSessionMiddleware, TRUSTED_USER_HEADERS
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor
from app.main import create_planning_service
from app.presentation.i18n import t
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
    st.error(t("auth.operation_failed", reference=reference))
    return True


def application_security() -> tuple[list[BaseRoute], list[Middleware]]:
    """Fail closed on missing configuration and compose supported Streamlit ASGI routes."""
    setup_logging()
    settings = AuthenticationConfig.from_environment(os.environ)
    if (st.get_option("server.trustedUserHeaders") != TRUSTED_USER_HEADERS
            or not st.get_option("server.enableCORS") or not st.get_option("server.enableXsrfProtection")
            or st.get_option("server.baseUrlPath")):
        raise ValueError("Enable the required Streamlit origin, XSRF, and session-binding configuration.")
    access = create_access_service(config.db_path, settings)
    client = create_oidc_client(settings, config.db_path, lambda: int(time()))

    def export_template(actor: Actor, project_id: int) -> str:
        service = create_planning_service(config.db_path, access=BusinessAccess(actor, access.policy))
        return service.export_project_template(project_id)

    routes = AuthenticationRoutes(client, access).routes() + DownloadRoutes(access, export_template).routes()
    middleware = [Middleware(BrowserSecurityMiddleware, config=settings),
                  Middleware(ApplicationSessionMiddleware, access=access, config=settings),
                  Middleware(SessionMiddleware, secret_key=settings.cookie_secret,
                             session_cookie=OIDC_COOKIE, max_age=600, same_site="lax",
                             https_only=settings.secure_cookies)]
    return routes, middleware


routes, middleware = application_security()
# Streamlit's AST-based launcher discovery requires a direct constructor assignment.
app = st.App(Path(__file__).with_name("streamlit_app.py"), routes=routes,
             middleware=middleware, on_script_error=script_error)
