"""Authenticated download delivery; every fetch uses current application policy."""

from collections.abc import Callable
from secrets import token_urlsafe

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.application.services.access import AccessService
from app.domain.access.models import AccessDenied, Actor
from app.infrastructure.authentication.http import SESSION_COOKIE
from app.shared.logging import get_logger


class DownloadRoutes:
    """Use the browser's server-verified session; URLs never carry credentials or data."""

    def __init__(self, access: AccessService, export_template: Callable[[Actor, int], str]) -> None:
        self.access, self.export_template = access, export_template

    def routes(self) -> list[Route]:
        """Expose a fixed attachment endpoint without cached or static media URLs."""
        return [Route("/downloads/projects/{project_id:int}/template.csv", self.project_template)]

    async def project_template(self, request: Request) -> Response:
        """Authorize and generate the requested template on each GET or HEAD request."""
        reference = token_urlsafe(16)
        try:
            actor = await run_in_threadpool(self.access.actor, request.cookies.get(SESSION_COOKIE, ""))
            project_id = request.path_params["project_id"]
            content = await run_in_threadpool(self.export_template, actor, project_id)
        except (AccessDenied, ValueError):
            return JSONResponse({"error": {"code": "download_denied", "reference": reference}},
                                status_code=403, headers={"Cache-Control": "no-store"})
        except Exception:
            # Deliberate HTTP boundary: no query contents, tokens, or exception payloads.
            get_logger(__name__).error("download.failed reference=%s", reference)
            return JSONResponse({"error": {"code": "download_failed", "reference": reference}},
                                status_code=503, headers={"Cache-Control": "no-store"})
        return Response(("\ufeff" + content).encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Content-Disposition": f'attachment; filename="project_{project_id}_template.csv"'})
