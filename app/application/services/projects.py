"""Project creation, editing, and deletion use cases."""

from app.domain.access.models import Permission
from app.application.ports.business_permissions import PermissionSnapshot


from app.application.ports.projects import PlanningProject, ProjectGateway, ProjectStore
from app.domain.projects.project import Project, normalize_project_name, prepare_project_values
from app.domain.projects.project_types import PropertyValue
from app.domain.projects.links import LinkValues, normalize_link
from app.domain.projects.wbs import WbsAllocation, WbsOption, normalize_allocations, validate_availability


def create_in_transaction(store: ProjectStore, project: Project) -> int:
    """Create within a caller-owned transaction, also used by bulk seeders."""
    project.name = normalize_project_name(project.name)
    _validate_priority(store, project.strategic_priority_id)
    project.dynamic_attributes = prepare_project_values(
        store.template(project.project_type_id), store.choices(),
        project.dynamic_attributes, creating=True,
    )
    return store.insert(project)


def _validate_priority(store: ProjectStore, identity: int | None) -> None:
    if identity is not None and (type(identity) is not int or identity not in store.strategic_priorities('en')):
        raise ValueError('Select a valid strategic priority.')


class ProjectService:
    """Coordinate validation and persistence without depending on a database."""

    def __init__(self, gateway: ProjectGateway) -> None:
        """Inject the transaction boundary."""
        self._gateway = gateway

    def permissions(self) -> PermissionSnapshot:
        """Describe current UI capabilities; writes independently reauthorize in their transaction."""
        return self._gateway.permission_snapshot()

    def get_project_by_id(self, project_id: int) -> Project | None:
        """Read a project's complete values, including inactive properties."""
        return self._gateway.run(lambda store: store.find(project_id))

    def get_planning_catalog(self, property_ids: tuple[str, ...] = ()) -> list[PlanningProject]:
        """Read project identities and only the dynamic filter properties requested."""
        return self._gateway.read_planning_catalog(property_ids)

    def exists(self, project_id: int) -> bool:
        """Check existence without loading custom values."""
        return self._gateway.run(lambda store: store.exists(project_id))

    def strategic_priorities(self, locale: str = 'en') -> dict[int, str]:
        """Read localized strategic-priority choices for project forms."""
        return self._gateway.run(lambda store: store.strategic_priorities(locale))

    def generate_project_id(self) -> int:
        """Suggest the next ID for display; the database allocates IDs on save."""
        return self._gateway.run(lambda store: store.next_id(), permission=Permission.CREATE)

    def create_project(
        self, project_id: int | None = None, name: str = "", status: str = "Draft",
        dynamic_attributes: dict[str, PropertyValue] | None = None,
        function_id: int | None = None, project_type_id: int | None = None,
        custom_links: list[LinkValues] | None = None,
        wbs_allocations: list[WbsAllocation] | None = None,
        strategic_priority_id: int | None = None,
    ) -> int:
        """Atomically validate the effective template and create a project."""
        name = normalize_project_name(name)
        links = [normalize_link(link["url"], link["alias"]) for link in custom_links or []]
        allocations = normalize_allocations(wbs_allocations) if wbs_allocations is not None else []
        submitted = {key: list(value) if isinstance(value, list) else value
                     for key, value in (dynamic_attributes or {}).items()}
        def operation(store: ProjectStore) -> int:
            type_id = store.default_type_id() if project_type_id is None else project_type_id
            created_id = create_in_transaction(store, Project(
                project_id, name, status, submitted, function_id, type_id, strategic_priority_id,
            ))
            if links:
                store.replace_links(created_id, links)
            if allocations:
                store.replace_wbs(created_id, allocations)
            return created_id
        return self._gateway.run(operation, write=True, permission=Permission.CREATE)

    def update_project(
        self, project_id: int, name: str, status: str, dynamic_attributes: dict[str, PropertyValue],
        function_id: int | None = None, project_type_id: int | None = None,
        custom_links: list[LinkValues] | None = None,
        wbs_allocations: list[WbsAllocation] | None = None,
        strategic_priority_id: int | None = None,
    ) -> bool:
        """Update active values atomically, preserving inactive values for later."""
        links = None if custom_links is None else [normalize_link(link["url"], link["alias"]) for link in custom_links]
        allocations = None if wbs_allocations is None else normalize_allocations(wbs_allocations)
        submitted = {key: list(value) if isinstance(value, list) else value for key, value in dynamic_attributes.items()}
        def operation(store: ProjectStore) -> bool:
            existing = store.find(project_id)
            if existing is None:
                return False
            clean_name = normalize_project_name(name)
            _validate_priority(store, strategic_priority_id)
            type_id = existing.project_type_id if project_type_id is None else project_type_id
            values = prepare_project_values(
                store.template(type_id), store.choices(), submitted,
                creating=False, existing=existing.dynamic_attributes,
            )
            store.update(Project(project_id, clean_name, status, values, function_id, type_id, strategic_priority_id))
            if existing.status == 'Cancelled' and status != 'Cancelled':
                try:
                    validate_availability(allocations if allocations is not None else store.wbs_allocations(project_id),
                                          store.wbs_options(project_id))
                except ValueError as exc:
                    raise ValueError('Cannot change the status of this cancelled project. '
                                     'Resolve its WBS allocation conflict before reactivating it. '
                                     + str(exc)) from exc
            if links is not None:
                store.replace_links(project_id, links)
            if allocations is not None:
                store.replace_wbs(project_id, allocations)
            return True
        return self._gateway.run(operation, write=True, permission=Permission.EDIT, project_ids=[project_id])

    def get_wbs_options(self, project_id: int | None = None) -> list[WbsOption]:
        """Read available whole percentages for a new or currently visible project."""
        permission = Permission.CREATE if project_id is None else Permission.READ
        return self._gateway.run(lambda store: store.wbs_options(project_id), permission=permission,
                                 project_ids=None if project_id is None else [project_id])

    def get_wbs_allocations(self, project_id: int) -> list[WbsAllocation]:
        """Read the project's WBS shares with current project authorization."""
        return self._gateway.run(lambda store: store.wbs_allocations(project_id), permission=Permission.READ, project_ids=[project_id])

    def get_links(self, project_id: int) -> list[LinkValues]:
        """Read custom links for project inspection or editing."""
        return self._gateway.run(lambda store: store.get_links(project_id))

    def delete_project(self, project_id: int) -> bool:
        """Remove a project and its dependent records in one transaction."""
        return self._gateway.run(lambda store: store.delete(project_id), write=True, permission=Permission.DELETE)
