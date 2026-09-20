"""Storage contracts for transactional project operations."""

from collections.abc import Callable, Collection
from app.domain.access.models import Permission
from app.application.ports.business_permissions import PermissionSnapshot


from typing import Protocol, TypedDict

from app.domain.projects.project import Project
from app.domain.projects.links import LinkValues
from app.domain.projects.project_types import PropertyValue, TemplateProperty
from app.application.ports.wbs import WbsStore


class PlanningProject(TypedDict):
    """Minimal project identity and requested filter values for planning."""

    id: int
    name: str
    status: str
    function_id: int | None
    project_type_id: int
    project_template: str
    dynamic_attributes: dict[str, PropertyValue]


class ProjectStore(WbsStore, Protocol):
    """Operations sharing the transaction supplied by ProjectGateway."""

    def find(self, project_id: int) -> Project | None: ...
    def default_type_id(self) -> int: ...
    def template(self, type_id: int) -> list[TemplateProperty]: ...
    def choices(self) -> dict[str, set[str]]: ...
    def insert(self, project: Project) -> int: ...
    def update(self, project: Project) -> None: ...
    def delete(self, project_id: int) -> bool: ...
    def exists(self, project_id: int) -> bool: ...
    def next_id(self) -> int: ...
    def strategic_priorities(self, locale: str) -> dict[int, str]: ...
    def get_links(self, project_id: int) -> list[LinkValues]: ...
    def replace_links(self, project_id: int, links: list[LinkValues]) -> None: ...


class ProjectGateway(Protocol):
    """Own the lifetime of a consistent read or atomic write transaction."""

    def run[Result](self, operation: Callable[[ProjectStore], Result], *, write: bool = False, permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Result:
        """Replay complete authorized use cases after a definite rollback."""
        ...
    def read_planning_catalog(self, property_ids: tuple[str, ...]) -> list[PlanningProject]: ...
    def permission_snapshot(self) -> PermissionSnapshot: ...
