"""Project-type use cases, independent of Streamlit, pandas, and SQLite."""

from app.domain.access.models import Permission
from app.application.ports.references import TypeReference


from app.application.ports.project_types import ProjectTypeGateway, ProjectTypeStore
from app.domain.projects.project_types import (
    ProjectType, PropertyApplicability, PropertyValue, TemplateProperty,
    make_applicability, normalize_details, resolve_template,
    validate_deletion, validate_rename,
)


class ProjectTypeService:
    """Coordinate domain validation and transactional project-type storage."""

    def __init__(self, gateway: ProjectTypeGateway) -> None:
        """Inject the persistence boundary; construction does not open a DB."""
        self._gateway = gateway

    def type_choices(self) -> list[TypeReference]:
        """Read only selector labels for an authorized project workflow."""
        with self._gateway.transaction() as store:
            return [TypeReference(row.id, row.name, row.is_general) for row in store.list_types()]

    def template_reference(self, type_id: int) -> list[TemplateProperty]:
        """Read the effective fields needed to inspect or edit a project."""
        with self._gateway.transaction() as store:
            return self._template(store, type_id)

    def get_all_types(self) -> list[ProjectType]:
        """List configured types in their display order."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return store.list_types()

    def create_type(self, name: str, description: str = "") -> int:
        """Validate details and create a project type."""
        clean_name, clean_description = normalize_details(name, description)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            return store.insert_type(clean_name, clean_description)

    def update_type(self, type_id: int, name: str, description: str = "") -> None:
        """Update details while protecting the built-in General name."""
        clean_name, clean_description = normalize_details(name, description)
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            project_type = self._require_type(store, type_id)
            validate_rename(project_type, name)
            store.update_type(type_id, clean_name, clean_description)

    def delete_type(self, type_id: int) -> None:
        """Guard references and delete in the same transaction."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            validate_deletion(
                store.find_type(type_id),
                has_projects=store.has_projects(type_id),
                has_exclusive_properties=store.has_exclusive_properties(type_id),
            )
            store.delete_type(type_id)

    def get_template(self, type_id: int) -> list[TemplateProperty]:
        """Resolve the type's effective required/default settings."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            return self._template(store, type_id)

    def get_applicability(self, param_id: str) -> PropertyApplicability:
        """Read a property's scope, rejecting an unknown property ID."""
        with self._gateway.transaction(permission=Permission.SHARED) as store:
            scope = store.get_applicability(param_id)
            if scope is None:
                raise ValueError("Unknown property")
            return scope

    def set_applicability(
        self, param_id: str, applies_to_all: bool, type_ids: list[int] | None = None,
    ) -> None:
        """Replace applicability atomically after validating selected scope."""
        scope = make_applicability(applies_to_all, type_ids or [])
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            store.set_applicability(param_id, scope)

    def save_rule(
        self, type_id: int, param_id: str, mandatory_override: bool | None = None,
        *, has_default: bool = False, default_value: PropertyValue = None,
    ) -> None:
        """Save rules only for applicable properties, with atomic defaults."""
        with self._gateway.transaction(write=True, permission=Permission.SHARED) as store:
            if param_id not in {p["param_id"] for p in self._template(store, type_id)}:
                raise ValueError("Property does not apply to this type")
            store.save_rule(
                type_id, param_id, mandatory_override,
                has_default=has_default, default_value=default_value,
            )

    @staticmethod
    def _require_type(store: ProjectTypeStore, type_id: int) -> ProjectType:
        project_type = store.find_type(type_id)
        if project_type is None:
            raise ValueError("Unknown project type")
        return project_type

    @classmethod
    def _template(cls, store: ProjectTypeStore, type_id: int) -> list[TemplateProperty]:
        cls._require_type(store, type_id)
        return resolve_template(
            store.property_definitions(), store.selected_properties(type_id),
            store.required_overrides(type_id), store.defaults(type_id),
        )
