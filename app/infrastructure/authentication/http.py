"""HTTP login, logout and activity endpoints with safe, bounded failure responses."""

from secrets import token_urlsafe

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from app.application.services.access import AccessService
from app.domain.access.models import AccessDenied
from app.infrastructure.authentication.oidc import ConfiguredOidcClient, verified_identity
from app.shared.logging import get_logger

SESSION_COOKIE = "eppm_session"
OIDC_COOKIE = "eppm_oidc"
logger = get_logger(__name__)


def require_same_origin(request: Request, origin: str) -> None:
    """Reject cross-origin and missing-origin state-changing browser requests."""
    if request.headers.get("origin") != origin:
        raise AccessDenied()


def failure_response(correlation: str, *, status: int = 401) -> JSONResponse:
    """Return a safe problem document without provider payloads or exception text."""
    return JSONResponse({"error": {"code": "authentication_required",
                                   "message": "Sign in to continue.",
                                   "reference": correlation}}, status_code=status,
                        headers={"Cache-Control": "no-store"})


class AuthenticationRoutes:
    """Bind request handlers to explicit services; never keep a mutable current user."""

    def __init__(self, client: ConfiguredOidcClient, access: AccessService) -> None:
        self.client, self.access = client, access
        self.config = client.authentication

    def routes(self) -> list[Route]:
        """Expose only fixed endpoints; bootstrap/recovery are never HTTP operations."""
        return [Route("/auth/login", self.login), Route("/auth/callback", self.callback),
                Route("/auth/logout", self.logout, methods=["POST"]),
                Route("/auth/activity", self.activity, methods=["POST"]),
                Route("/auth/session", self.session)]

    async def login(self, request: Request) -> Response:
        """Start a fresh provider login with exact callback, state, nonce and PKCE."""
        try:
            params: dict[str, str | int] = {"prompt": "login", "max_age": 0}
            if self.config.mfa_acr_values:
                params["acr_values"] = " ".join(self.config.mfa_acr_values)
            response = await self.client.authorize_redirect(request, self.config.callback_url, **params)
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception:
            # Deliberate HTTP boundary: never include provider errors/credentials in logs.
            return self._failure("oidc.start_failed", status=503)

    async def callback(self, request: Request) -> Response:
        """Persist a new pending account only after complete library token validation."""
        try:
            identity = await verified_identity(self.client, request)
            previous = request.cookies.get(SESSION_COOKIE)
            cookie = await run_in_threadpool(self.access.sign_in, identity, previous)
        except Exception:
            request.session.clear()
            return self._failure("oidc.callback_failed")
        request.session.clear()
        response = RedirectResponse(self.config.origin + "/", status_code=303)
        response.headers["Cache-Control"] = "no-store"
        response.set_cookie(SESSION_COOKIE, cookie, httponly=True, secure=self.config.secure_cookies,
                            samesite="lax", path="/", max_age=self.config.absolute_seconds)
        return response

    async def logout(self, request: Request) -> Response:
        """Revoke the shared browser session and remove its opaque cookie."""
        try:
            require_same_origin(request, self.config.origin)
            actor = await run_in_threadpool(self.access.actor, request.cookies.get(SESSION_COOKIE, ""))
            await run_in_threadpool(self.access.logout, actor)
        except AccessDenied:
            # Origin remains mandatory even if an already expired session is logged out.
            if request.headers.get("origin") != self.config.origin:
                return self._failure("session.origin_denied", status=403)
        except Exception:
            return self._failure("session.logout_failed", status=503)
        request.session.clear()
        response = Response(status_code=204, headers={"Cache-Control": "no-store"})
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True,
                               secure=self.config.secure_cookies, samesite="lax")
        return response

    async def activity(self, request: Request) -> Response:
        """Extend idle time only on explicit, same-origin user interaction events."""
        try:
            require_same_origin(request, self.config.origin)
            if request.headers.get("x-eppm-activity") != "user-interaction":
                raise AccessDenied()
            actor = await run_in_threadpool(self.access.actor, request.cookies.get(SESSION_COOKIE, ""))
            await run_in_threadpool(self.access.activity, actor)
            return Response(status_code=204, headers={"Cache-Control": "no-store"})
        except Exception:
            return self._failure("session.activity_denied", status=403)

    async def session(self, request: Request) -> Response:
        """Check cross-tab revocation without updating last activity or exposing profile data."""
        try:
            actor = await run_in_threadpool(self.access.actor, request.cookies.get(SESSION_COOKIE, ""))
            account = await run_in_threadpool(self.access.account, actor)
            return JSONResponse({"status": account["status"]}, headers={"Cache-Control": "no-store"})
        except Exception:
            return self._failure("session.expired")

    @staticmethod
    def _failure(event: str, *, status: int = 401) -> Response:
        correlation = token_urlsafe(16)
        logger.warning("%s reference=%s", event, correlation)
        return failure_response(correlation, status=status)
