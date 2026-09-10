"""Authorized, uncached delivery of versioned WBS budget CSV attachments."""

from collections.abc import Callable
from secrets import token_urlsafe

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.application.services.access import AccessService
from app.domain.access.models import Actor
from app.infrastructure.authentication.http import SESSION_COOKIE
from app.shared.logging import get_logger


class FinanceDownloadRoutes:
    """Regenerate every attachment after validating the current browser identity."""

    def __init__(self, access: AccessService, export: Callable[[Actor, int], str]) -> None:
        self.access, self.export = access, export

    def routes(self) -> list[Route]:
        """Expose a saved snapshot identifier without embedding financial data in URLs."""
        return [Route("/downloads/finance/{snapshot_id:int}/budget.csv", self.download)]

    async def download(self, request: Request) -> Response:
        """Validate the session and active-account read policy on GET and HEAD."""
        reference = token_urlsafe(16)
        try:
            actor = await run_in_threadpool(self.access.actor, request.cookies.get(SESSION_COOKIE, ""))
            snapshot_id = request.path_params["snapshot_id"]
            content = await run_in_threadpool(self.export, actor, snapshot_id)
        except ValueError:
            return JSONResponse({"error": {"code": "download_denied", "reference": reference}},
                                status_code=403, headers={"Cache-Control": "no-store"})
        except Exception:
            # Deliberate HTTP boundary: do not expose SQL, credentials or financial values.
            get_logger(__name__).error("finance.download_failed reference=%s", reference)
            return JSONResponse({"error": {"code": "download_failed", "reference": reference}},
                                status_code=503, headers={"Cache-Control": "no-store"})
        return Response(("\ufeff" + content).encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Content-Disposition": f'attachment; filename="budget_{snapshot_id}.csv"'})
