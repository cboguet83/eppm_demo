"""Business-administrator maintenance of the shared WBS catalog."""

from app.application.ports.projects import ProjectGateway
from app.domain.access.models import Permission
from app.domain.projects.wbs import WbsOption, normalize_wbs


class WbsService:
    """Authorize catalog maintenance independently from project editing."""

    def __init__(self, gateway: ProjectGateway) -> None:
        """Inject the existing authorized transaction boundary."""
        self._gateway = gateway

    def can_manage(self) -> bool:
        """Return current UI capability; each operation reauthorizes."""
        return self._gateway.permission_snapshot().allows(Permission.SHARED)

    def list_catalog(self) -> list[WbsOption]:
        """Read catalog descriptions and unallocated totals for administrators."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.wbs_options(None)

    def save(self, code: str, description: str = "", wbs_id: int | None = None) -> int:
        """Create or edit a reference without changing its project assignments."""
        code, description = normalize_wbs(code, description)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.save_wbs(code, description, wbs_id)

    def delete(self, wbs_id: int) -> None:
        """Delete an unused reference; assigned WBS entries must be detached first."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            store.delete_wbs(wbs_id)
