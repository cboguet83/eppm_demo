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

    def __init__(self, access: AccessService, export_template: Callable[[Actor, int], str], *,
                 export_organization: Callable[[Actor, str], str] | None = None,
                 export_pools: Callable[[Actor, bool, bool], str] | None = None,
                 export_teams: Callable[[Actor, bool, bool], str] | None = None,
                 export_functions: Callable[[Actor, bool, bool], str] | None = None) -> None:
        """Bind authenticated project and optional organization exporters."""
        self.access, self.export_template = access, export_template
        self.export_organization = export_organization
        self.export_pools = export_pools
        self.export_teams = export_teams
        self.export_functions = export_functions

    def routes(self) -> list[Route]:
        """Expose a fixed attachment endpoint without cached or static media URLs."""
        routes = [Route("/downloads/projects/{project_id:int}/template.csv", self.project_template)]
        if self.export_organization is not None:
            routes.append(Route('/downloads/organization/{catalog:str}.csv', self.organization_catalog))
        if self.export_pools is not None:
            routes.append(Route('/downloads/resource-pools/{catalog:str}.csv', self.pool_catalog))
        if self.export_teams is not None:
            routes.append(Route('/downloads/teams/{catalog:str}.csv', self.team_catalog))
        if self.export_functions is not None:
            routes.append(Route('/downloads/functions/{catalog:str}.csv', self.function_catalog))
        return routes

    async def function_catalog(self, request: Request) -> Response:
        """Deliver function catalogs and templates after current authorization."""
        return await self._resource_catalog(request, self.export_functions, 'functions', 'functions')

    async def pool_catalog(self, request: Request) -> Response:
        """Deliver pool CSV through current session and shared-management checks."""
        return await self._resource_catalog(request, self.export_pools, 'pools', 'resource_pools')

    async def team_catalog(self, request: Request) -> Response:
        """Deliver team CSV with the same authenticated download contract."""
        return await self._resource_catalog(request, self.export_teams, 'teams', 'teams')

    async def _resource_catalog(self, request: Request, export: Callable[[Actor, bool, bool], str] | None,
                                catalog_name: str, filename: str) -> Response:
        """Validate visibility and generate a no-store catalog attachment."""
        reference = token_urlsafe(16)
        try:
            actor = await run_in_threadpool(self.access.actor, request.cookies.get(SESSION_COOKIE, ''))
            catalog = request.path_params['catalog']
            visibility = request.query_params.get('include_deleted', 'false')
            if catalog not in {catalog_name, 'template'} or visibility not in {'true', 'false'} or export is None:
                raise ValueError('Unknown resource catalog export.')
            content = await run_in_threadpool(export, actor, visibility == 'true', catalog == 'template')
        except (AccessDenied, ValueError):
            return JSONResponse({'error': {'code': 'download_denied', 'reference': reference}},
                                status_code=403, headers={'Cache-Control': 'no-store'})
        except Exception:
            # Deliberate HTTP boundary: return no storage or catalog details.
            get_logger(__name__).error('resource_catalog_download.failed reference=%s', reference)
            return JSONResponse({'error': {'code': 'download_failed', 'reference': reference}},
                                status_code=503, headers={'Cache-Control': 'no-store'})
        filename += '_template.csv' if catalog == 'template' else '.csv'
        return Response(('\ufeff' + content).encode('utf-8'), media_type='text/csv; charset=utf-8',
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'Content-Disposition': f'attachment; filename="{filename}"'})

    async def organization_catalog(self, request: Request) -> Response:
        """Reauthorize each organization attachment, including employee information."""
        reference = token_urlsafe(16)
        try:
            actor = await run_in_threadpool(self.access.actor, request.cookies.get(SESSION_COOKIE, ''))
            catalog = request.path_params['catalog']
            if catalog not in {'functions', 'function_types', 'teams', 'employees'} or self.export_organization is None:
                raise ValueError('Unknown organization catalog.')
            content = await run_in_threadpool(self.export_organization, actor, catalog)
        except (AccessDenied, ValueError):
            return JSONResponse({'error': {'code': 'download_denied', 'reference': reference}},
                                status_code=403, headers={'Cache-Control': 'no-store'})
        except Exception:
            # Deliberate HTTP boundary; never expose employee data or error payloads.
            get_logger(__name__).error('organization_download.failed reference=%s', reference)
            return JSONResponse({'error': {'code': 'download_failed', 'reference': reference}},
                                status_code=503, headers={'Cache-Control': 'no-store'})
        return Response(('\ufeff' + content).encode('utf-8'), media_type='text/csv; charset=utf-8',
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'Content-Disposition': f'attachment; filename="{catalog}.csv"'})

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
