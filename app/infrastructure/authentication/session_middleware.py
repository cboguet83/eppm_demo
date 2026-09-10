"""Bind Streamlit connections to real browser sessions and recheck live traffic."""

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.application.services.access import AccessService
from app.domain.access.models import AccessDenied, Actor
from app.infrastructure.authentication.http import SESSION_COOKIE
from app.shared.config.authentication import AuthenticationConfig

SESSION_HEADER = "x-eppm-browser-session"
TRUSTED_USER_HEADERS = {SESSION_HEADER: "eppm_browser_session"}


class ApplicationSessionMiddleware:
    """Overwrite browser-supplied identity headers and validate both message directions."""

    def __init__(self, app: ASGIApp, *, access: AccessService, config: AuthenticationConfig) -> None:
        self.app, self.access, self.config = app, access, config

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Deny native data transports and bind all WebSockets to verified sessions."""
        if scope["type"] == "http" and scope["path"].startswith(("/media/", "/_stcore/upload_file/", "/_stcore/metrics")):
            await JSONResponse({"error": {"code": "transport_denied"}}, status_code=403)(scope, receive, send)
            return
        if scope["type"] != "websocket":
            await self.app(scope, receive, send)
            return
        cookie = HTTPConnection(scope).cookies.get(SESSION_COOKIE, "")
        actor, status, revision = await self._identity(cookie)
        scope = dict(scope)
        scope["headers"] = list(scope["headers"])
        binding = self.config.session_binding(actor.session_hash if actor else "anonymous", status, revision)
        MutableHeaders(scope=scope)[SESSION_HEADER] = binding
        closed = False

        async def valid() -> bool:
            if actor is None:
                return True  # Anonymous runtimes can display only the login gate.
            current, current_status, current_revision = await self._identity(cookie)
            return (current is not None and current.session_hash == actor.session_hash
                    and current_status == status and current_revision == revision)

        async def close() -> None:
            nonlocal closed
            if not closed:
                closed = True
                await send({"type": "websocket.close", "code": 1008})

        async def guarded_receive() -> Message:
            message = await receive()
            if message["type"] == "websocket.receive" and not await valid():
                await close()
                return {"type": "websocket.disconnect", "code": 1008}
            return message

        async def guarded_send(message: Message) -> None:
            if closed:
                return
            if message["type"] == "websocket.send" and not await valid():
                await close()
                return
            await send(message)

        await self.app(scope, guarded_receive, guarded_send)

    async def _identity(self, cookie: str) -> tuple[Actor | None, str, int]:
        try:
            return await run_in_threadpool(self.access.browser_identity, cookie)
        except AccessDenied:
            return None, "anonymous", -1
