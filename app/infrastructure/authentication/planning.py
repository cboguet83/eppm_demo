"""Authenticated task and capacity-badge reads that do not trigger Streamlit reruns."""

from collections.abc import Callable
import json
import re
from secrets import token_urlsafe

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.application.services.access import AccessService
from app.application.exceptions import PlanningRevisionChanged, PortfolioRevisionChanged
from app.domain.access.models import AccessDenied, Actor
from app.infrastructure.authentication.http import SESSION_COOKIE
from app.shared.logging import get_logger


class PlanningReadRoutes:
    """Reauthorize each batch independently of browser scope/permission hints."""

    def __init__(
        self, access: AccessService, read_tasks: Callable[[Actor, list[int], str], dict[str, object]], *,
        read_allocations: Callable[[Actor, list[int], str], dict[str, object]] | None = None,
        read_task_sources: Callable[[Actor, list[int], dict[int, str]], dict[str, object]] | None = None,
    ) -> None:
        """Share the bounded, authenticated read transport across tasks and badges."""
        self.access, self.read_tasks = access, read_tasks
        self.read_allocations = read_allocations
        self.read_task_sources = read_task_sources

    def routes(self) -> list[Route]:
        """Register only the bounded read transport; edits keep their existing path."""
        routes = [Route("/api/planning/tasks", self.tasks, methods=["POST"])]
        if self.read_allocations is not None:
            routes.append(Route("/api/portfolio/allocations", self.allocations, methods=["POST"]))
        return routes

    async def tasks(self, request: Request) -> JSONResponse:
        """Return current authorized tasks, or a safe no-store error response."""
        return await self._read(request, self.read_tasks, "planning", source_reader=self.read_task_sources)

    async def allocations(self, request: Request) -> JSONResponse:
        """Return current authorized capacity badges without blocking row rendering."""
        assert self.read_allocations is not None
        return await self._read(request, self.read_allocations, "portfolio")

    async def _read(
        self, request: Request, reader: Callable[[Actor, list[int], str], dict[str, object]], kind: str,
        *, source_reader: Callable[[Actor, list[int], dict[int, str]], dict[str, object]] | None = None,
    ) -> JSONResponse:
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        reference = token_urlsafe(16)
        try:
            actor = await run_in_threadpool(self.access.actor, request.cookies.get(SESSION_COOKIE, ""))
            content = bytearray()
            async for part in request.stream():
                if len(content) + len(part) > 4096:
                    raise ValueError()
                content.extend(part)
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError()
            ids = data.get("project_ids")
            if (not isinstance(ids, list) or not 1 <= len(ids) <= 25
                    or any(type(pid) is not int or not 0 < pid < 2**63 for pid in ids)):
                raise ValueError()
            for key in ("revision", "scope_token", "nonce"):
                if not isinstance(data.get(key), str) or not 1 <= len(data[key]) <= 128:
                    raise ValueError()
            ids = list(dict.fromkeys(ids))
            sources = data.get('source_tokens')
            if sources is not None:
                if (source_reader is None or not isinstance(sources, dict) or set(sources) != set(map(str, ids))
                        or any(not isinstance(token, str) or re.fullmatch('[0-9a-f]{64}', token) is None
                               for token in sources.values())):
                    raise ValueError()
                payload = await run_in_threadpool(source_reader, actor, ids, {int(pid): token for pid, token in sources.items()})
            else:
                payload = await run_in_threadpool(reader, actor, ids, data["revision"])
            payload.update(scope_token=data["scope_token"], nonce=data["nonce"])
            return JSONResponse(payload, headers=headers)
        except AccessDenied:
            code, status = f"{kind}_denied", 403
        except (PlanningRevisionChanged, PortfolioRevisionChanged):
            code, status = f"{kind}_changed", 409
        except (ValueError, UnicodeError):
            code, status = f"invalid_{kind}_request", 400
        except Exception:
            # Deliberate HTTP boundary; do not expose query, identity or exception data.
            get_logger(__name__).error("%s.read_failed reference=%s", kind, reference)
            code, status = f"{kind}_unavailable", 503
        return JSONResponse({"error": {"code": code, "reference": reference}}, status_code=status, headers=headers)
