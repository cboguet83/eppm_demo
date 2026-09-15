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
from app.infrastructure.authentication.planning import PlanningReadRoutes
from app.infrastructure.authentication.session_middleware import ApplicationSessionMiddleware, TRUSTED_USER_HEADERS
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor
from app.main import create_planning_service
from app.presentation.i18n import t
from app.infrastructure.authentication.middleware import BrowserSecurityMiddleware
from app.infrastructure.authentication.oidc import create_oidc_client
from app.infrastructure.postgresql.oidc_state import PostgresOidcState
from app.runtime import RuntimeResources, process_runtime
from app.security import create_access_service
from app.shared.config.authentication import AuthenticationConfig
from app.shared.logging import get_logger, setup_logging


def script_error(error: Exception) -> bool:
    """Suppress internal exception details in browser-rendered scripts and callbacks."""
    reference = token_urlsafe(16)
    location = error.__traceback__
    while location is not None and location.tb_next is not None:
        location = location.tb_next
    # Record code location and category, never the exception message, source line,
    # local variables or provider payload. The browser receives only its reference.
    get_logger(__name__).error(
        "application.operation_failed reference=%s exception=%s source=%s line=%s",
        reference, type(error).__name__,
        Path(location.tb_frame.f_code.co_filename).name if location is not None else "unknown",
        location.tb_lineno if location is not None else 0,
    )
    st.error(t("auth.operation_failed", reference=reference))
    return True


def application_security(resources: RuntimeResources) -> tuple[list[BaseRoute], list[Middleware]]:
    """Fail closed on missing configuration and compose supported Streamlit ASGI routes."""
    setup_logging()
    settings = AuthenticationConfig.from_environment(os.environ)
    if (st.get_option("server.trustedUserHeaders") != TRUSTED_USER_HEADERS
            or not st.get_option("server.enableCORS") or not st.get_option("server.enableXsrfProtection")
            or st.get_option("server.baseUrlPath")):
        raise ValueError("Enable the required Streamlit origin, XSRF, and session-binding configuration.")
    access = create_access_service(resources, settings)
    client = create_oidc_client(settings, PostgresOidcState(resources.database, resources.key, lambda: int(time())))

    def export_template(actor: Actor, project_id: int) -> str:
        service = create_planning_service(resources, access=BusinessAccess(actor, access.policy))
        return service.export_project_template(project_id)

    def export_organization(actor: Actor, catalog: str) -> str:
        from app.main import create_organization_service

        service = create_organization_service(resources, access=BusinessAccess(actor, access.policy))
        return service.export_csv(catalog)

    def read_tasks(actor: Actor, project_ids: list[int], revision: str, *,
                   source_tokens: dict[int, str] | None = None) -> dict[str, object]:
        from app.domain.access.models import Permission
        from app.main import create_planning_workspace
        from app.presentation.components.planning_transport import read_planning_batch

        business_access = BusinessAccess(actor, access.policy)
        access.gateway.run(lambda store: business_access.require(store, Permission.READ, project_ids), actor=actor)
        workspace = create_planning_workspace(resources, access=business_access)
        return read_planning_batch(workspace, project_ids, revision, source_tokens=source_tokens)

    def read_task_sources(actor: Actor, project_ids: list[int], sources: dict[int, str]) -> dict[str, object]:
        return read_tasks(actor, project_ids, '', source_tokens=sources)

    def read_allocations(actor: Actor, project_ids: list[int], revision: str) -> dict[str, object]:
        from app.domain.access.models import Permission
        from app.main import create_portfolio_service

        business_access = BusinessAccess(actor, access.policy)
        access.gateway.run(lambda store: business_access.require(store, Permission.READ, project_ids), actor=actor)
        service = create_portfolio_service(resources, access=business_access)
        return service.get_allocation_badges(project_ids, revision)

    from app.main import create_finance_service
    from app.infrastructure.authentication.finance import FinanceDownloadRoutes

    def export_budget(actor: Actor, snapshot_id: int) -> str:
        return create_finance_service(resources, access=BusinessAccess(actor, access.policy)).export(snapshot_id)

    routes = (AuthenticationRoutes(client, access).routes()
              + DownloadRoutes(access, export_template, export_organization=export_organization).routes()
              + FinanceDownloadRoutes(access, export_budget).routes()
              + PlanningReadRoutes(access, read_tasks, read_allocations=read_allocations,
                                   read_task_sources=read_task_sources).routes())
    middleware = [Middleware(BrowserSecurityMiddleware, config=settings),
                  Middleware(ApplicationSessionMiddleware, access=access, config=settings),
                  Middleware(SessionMiddleware, secret_key=settings.cookie_secret,
                             session_cookie=OIDC_COOKIE, max_age=600, same_site="lax",
                             https_only=settings.secure_cookies)]
    return routes, middleware


resources = process_runtime()
routes, middleware = application_security(resources)
# Streamlit's AST-based launcher discovery requires a direct constructor assignment.
app = st.App(Path(__file__).with_name("streamlit_app.py"), routes=routes,
             middleware=middleware, on_script_error=script_error, lifespan=resources.lifespan)
