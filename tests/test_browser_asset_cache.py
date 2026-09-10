"""Serve real installed framework bundles without caching application responses."""

from pathlib import Path
import secrets

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient
from streamlit.file_util import get_static_dir
from streamlit.web.server.starlette.starlette_static_routes import create_streamlit_static_assets_routes

from app.infrastructure.authentication.middleware import BrowserSecurityMiddleware
from app.shared.config.authentication import AuthenticationConfig


@pytest.fixture
def settings() -> AuthenticationConfig:
    """Keep the actual development origin checks without requiring an OIDC login."""
    return AuthenticationConfig(
        "development", "http://localhost:8080/realms/eppm", "cache-test",
        secrets.token_urlsafe(32), "http://localhost:8501",
        secrets.token_urlsafe(48), local_http=True,
    )


def _bundle_url(kind: str) -> str:
    directory = Path(get_static_dir())
    pattern = "static/js/Multiselect.*.js" if kind == "js" else "static/css/*.css"
    return "/" + next(directory.glob(pattern)).relative_to(directory).as_posix()


@pytest.mark.parametrize("kind,media_type", [
    ("js", ("application/javascript", "text/javascript")), ("css", ("text/css",)),
])
def test_actual_framework_bundles_keep_native_cache_headers_and_conditional_reads(settings, kind, media_type):
    app = Starlette(routes=create_streamlit_static_assets_routes(None), middleware=[
        Middleware(BrowserSecurityMiddleware, config=settings),
    ])
    with TestClient(app, base_url=settings.origin) as browser:
        url = _bundle_url(kind)
        response = browser.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(media_type)
        assert "public" in response.headers["cache-control"]
        assert "immutable" in response.headers["cache-control"]
        assert "max-age=" in response.headers["cache-control"]
        assert "set-cookie" not in response.headers
        assert response.headers["x-content-type-options"] == "nosniff"
        head = browser.head(url)
        assert not head.content and head.headers["cache-control"] == response.headers["cache-control"]
        unchanged = browser.get(url, headers={"If-None-Match": response.headers["etag"]})
        assert unchanged.status_code == 304 and not unchanged.content
        assert "no-store" not in unchanged.headers.get("cache-control", "")
        partial = browser.get(url, headers={"Range": "bytes=0-15"})
        assert partial.status_code == 206
        assert partial.headers["cache-control"] == response.headers["cache-control"]


def test_missing_old_bundle_fallback_and_initial_html_remain_uncached(settings):
    app = Starlette(routes=create_streamlit_static_assets_routes(None), middleware=[
        Middleware(BrowserSecurityMiddleware, config=settings),
    ])
    with TestClient(app, base_url=settings.origin) as browser:
        for url in ("/", "/static/js/Multiselect.missing-version.js"):
            response = browser.get(url)
            assert response.headers["content-type"].startswith("text/html")
            assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path,status,method,extra_headers", [
    ("/auth/session", 200, "GET", {}),
    ("/auth/callback", 303, "GET", {}),
    ("/downloads/projects/1/template.csv", 200, "GET", {}),
    ("/api/planning/tasks", 200, "POST", {}),
    ("/app/static/project.json", 200, "GET", {}),
    ("/component/custom/entry.js", 200, "GET", {}),
    ("/static/js/entry.version.js", 403, "GET", {}),
    ("/static/js/entry.version.js", 500, "GET", {}),
    ("/static/js/entry.version.js", 200, "POST", {}),
    ("/static/js/entry.version.js", 200, "GET", {"set-cookie": "test-preference=value"}),
    ("/static/js/entry.version.js", 200, "GET", {"cache-control": "private, max-age=30"}),
])
def test_only_successful_cookie_free_public_framework_bundles_can_be_cached(settings, path, status, method, extra_headers):
    async def response(request):
        return Response("response", status_code=status, headers={
            "cache-control": "public, immutable, max-age=31536000", **extra_headers,
        })

    app = Starlette(routes=[Route(path, response, methods=[method])], middleware=[
        Middleware(BrowserSecurityMiddleware, config=settings),
    ])
    with TestClient(app, base_url=settings.origin) as browser:
        result = browser.request(method, path, headers={"origin": settings.origin}, follow_redirects=False)
        assert result.status_code == status
        assert result.headers["cache-control"] == "no-store"
