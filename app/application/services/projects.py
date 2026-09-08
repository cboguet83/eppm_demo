"""Project creation, editing, and deletion use cases."""

from app.application.ports.projects import PlanningProject, ProjectGateway, ProjectStore
from app.domain.projects.project import Project, normalize_project_name, prepare_project_values
from app.domain.projects.project_types import PropertyValue


def create_in_transaction(store: ProjectStore, project: Project) -> int:
    """Create within a caller-owned transaction, also used by bulk seeders."""
    project.name = normalize_project_name(project.name)
    project.dynamic_attributes = prepare_project_values(
        store.template(project.project_type_id), store.choices(),
        project.dynamic_attributes, creating=True,
    )
    return store.insert(project)


class ProjectService:
    """Coordinate validation and persistence without depending on a database."""

    def __init__(self, gateway: ProjectGateway) -> None:
        """Inject the transaction boundary."""
        self._gateway = gateway

    def get_project_by_id(self, project_id: int) -> Project | None:
        """Read a project's complete values, including inactive properties."""
        with self._gateway.transaction() as store:
            return store.find(project_id)

    def get_planning_catalog(self, property_ids: tuple[str, ...] = ()) -> list[PlanningProject]:
        """Read project identities and only the dynamic filter properties requested."""
        return self._gateway.read_planning_catalog(property_ids)

    def exists(self, project_id: int) -> bool:
        """Check existence without loading custom values."""
        with self._gateway.transaction() as store:
            return store.exists(project_id)

    def generate_project_id(self) -> int:
        """Suggest the next ID for display; the database allocates IDs on save."""
        with self._gateway.transaction() as store:
            return store.next_id()

    def create_project(
        self, project_id: int | None = None, name: str = "", status: str = "Draft",
        planned_budget: float = 0.0, actual_budget: float = 0.0,
        dynamic_attributes: dict[str, PropertyValue] | None = None,
        function_id: int | None = None, project_type_id: int | None = None,
    ) -> int:
        """Atomically validate the effective template and create a project."""
        name = normalize_project_name(name)
        with self._gateway.transaction(write=True) as store:
            type_id = store.default_type_id() if project_type_id is None else project_type_id
            return create_in_transaction(store, Project(
                project_id, name, status, planned_budget, actual_budget,
                dynamic_attributes or {}, function_id, type_id,
            ))

    def update_project(
        self, project_id: int, name: str, status: str, planned_budget: float,
        actual_budget: float, dynamic_attributes: dict[str, PropertyValue],
        function_id: int | None = None, project_type_id: int | None = None,
    ) -> bool:
        """Update active values atomically, preserving inactive values for later."""
        with self._gateway.transaction(write=True) as store:
            existing = store.find(project_id)
            if existing is None:
                return False
            name = normalize_project_name(name)
            type_id = existing.project_type_id if project_type_id is None else project_type_id
            values = prepare_project_values(
                store.template(type_id), store.choices(), dynamic_attributes,
                creating=False, existing=existing.dynamic_attributes,
            )
            store.update(Project(project_id, name, status, planned_budget,
                                 actual_budget, values, function_id, type_id))
            return True

    def delete_project(self, project_id: int) -> bool:
        """Remove a project and its dependent records in one transaction."""
        with self._gateway.transaction(write=True) as store:
            return store.delete(project_id)
