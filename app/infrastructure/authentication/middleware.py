"""Common origin and security-header enforcement for HTTP and WebSocket traffic."""

from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.shared.config.authentication import AuthenticationConfig


class BrowserSecurityMiddleware:
    """Use the configured public origin instead of trusting browser or proxy headers."""

    def __init__(self, app: ASGIApp, *, config: AuthenticationConfig) -> None:
        self.app, self.config = app, config

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject foreign hosts/origins and prevent caching or embedding sensitive views."""
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        foreign_host = headers.get("host") != urlsplit(self.config.origin).netloc
        changes_state = scope["type"] == "websocket" or scope.get("method") not in {"GET", "HEAD", "OPTIONS"}
        foreign_origin = changes_state and headers.get("origin") != self.config.origin
        if foreign_host or foreign_origin:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                response = JSONResponse({"error": {"code": "origin_denied"}}, status_code=403)
                await response(scope, receive, send)
            return

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["Cache-Control"] = "no-store"
                response_headers["X-Content-Type-Options"] = "nosniff"
                response_headers["X-Frame-Options"] = "SAMEORIGIN"
                response_headers["Referrer-Policy"] = "no-referrer"
                response_headers["Content-Security-Policy"] = "frame-ancestors 'self'; object-src 'none'; base-uri 'self'"
                if self.config.secure_cookies:
                    response_headers["Strict-Transport-Security"] = "max-age=31536000"
            await send(message)

        await self.app(scope, receive, secured_send)
