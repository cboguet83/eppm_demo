"""Transactional use cases for groups, property definitions, and choices."""

from dataclasses import replace
import re

from app.application.ports.schema import SchemaGateway, SchemaSnapshot
from app.domain.projects.project_types import make_applicability
from app.domain.projects.schema import (
    SchemaGroup, SchemaParameter, SchemaParamOption, next_group_order,
    next_parameter_id, normalize_group, normalize_option, normalize_parameter,
    validate_option_deletion, validate_property_deletion, validate_property_type_change,
)


class SchemaService:
    """Coordinate schema rules and persistence within application transactions."""

    def __init__(self, gateway: SchemaGateway) -> None:
        """Inject storage without opening a connection at construction."""
        self._gateway = gateway

    def get_snapshot(self) -> SchemaSnapshot:
        """Read all editor catalogs in one consistent snapshot."""
        with self._gateway.transaction() as store:
            return SchemaSnapshot(store.groups(), store.parameters(), store.options())

    def get_all_groups(self) -> list[SchemaGroup]:
        """Read groups in display order."""
        with self._gateway.transaction() as store:
            return store.groups()

    def get_all_parameters(self) -> list[SchemaParameter]:
        """Read property definitions without project values or options."""
        with self._gateway.transaction() as store:
            return store.parameters()

    def get_all_options(self) -> list[SchemaParamOption]:
        """Read choices ordered by display order and ID."""
        with self._gateway.transaction() as store:
            return store.options()

    def get_alias_translations(self, locale: str) -> dict[str, str]:
        """Read explicit translations; presentation supplies default alias fallbacks."""
        with self._gateway.transaction() as store:
            return store.alias_translations(locale.strip().lower())

    def set_alias_translation(self, param_id: str, locale: str, alias: str) -> None:
        """Save a localized alias, or remove it when blank, for an existing property."""
        locale = locale.strip().lower()
        if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", locale):
            raise ValueError("Use a language code such as en, fr, or de.")
        with self._gateway.transaction(write=True) as store:
            if store.find_parameter(param_id) is None:
                raise ValueError("Unknown property")
            store.set_alias_translation(param_id, locale, alias.strip())

    def get_next_available_group_order(self) -> int:
        """Suggest the first unused positive group order."""
        with self._gateway.transaction() as store:
            return next_group_order(group.display_order for group in store.groups())

    def generate_param_id(self) -> str:
        """Preview the next property ID; automatic creation allocates under lock."""
        with self._gateway.transaction() as store:
            return next_parameter_id(store.parameter_identifiers())

    def create_group(
        self, group_name: str, display_order: int, *, auto_assign_order: bool = False,
    ) -> int:
        """Create a group, optionally resolving order collisions as the UI does."""
        name, order = normalize_group(group_name, display_order)
        with self._gateway.transaction(write=True) as store:
            if auto_assign_order:
                occupied = {group.display_order for group in store.groups()}
                if order in occupied:
                    order = next_group_order(occupied)
            return store.insert_group(name, order)

    def update_group(self, group_id: int, group_name: str, display_order: int) -> bool:
        """Update a group's details; conflicting names/orders remain rejected."""
        name, order = normalize_group(group_name, display_order)
        with self._gateway.transaction(write=True) as store:
            return store.update_group(group_id, name, order)

    def delete_group(self, group_id: int) -> bool:
        """Ungroup its properties and delete the group in the same transaction."""
        with self._gateway.transaction(write=True) as store:
            store.ungroup_parameters(group_id)
            return store.delete_group(group_id)

    def create_parameter(
        self, param_id: str | None, group_id: int | None, param_name: str, param_type: str,
        mandatory: bool = False, alias: str | None = None, applies_to_all: bool = True,
        project_type_ids: list[int] | None = None, *, initial_options: list[str] | None = None,
    ) -> str:
        """Create a definition, applicability, and initial choices atomically.

        Args:
            param_id: Explicit stable ID, or None to allocate during the write.
            group_id: Optional display group.
            param_name: User-facing property name.
            param_type: Supported property kind.
            mandatory: Required setting inherited by effective templates.
            alias: Optional alternative display name.
            applies_to_all: Include the property in current and future types.
            project_type_ids: Selected types when all-types applicability is off.
            initial_options: Ordered choices to insert in the same transaction.

        Returns:
            The created property's normalized or allocated ID.
        """
        parameter = normalize_parameter(SchemaParameter(
            param_id if param_id is not None else "PRM_AUTO", param_name, param_type,
            group_id, mandatory, alias, applies_to_all,
        ))
        scope = make_applicability(applies_to_all, project_type_ids or [])
        options = [normalize_option(value, index) for index, value in enumerate(initial_options or [], 1)]
        with self._gateway.transaction(write=True) as store:
            if param_id is None:
                parameter = replace(parameter, param_id=next_parameter_id(store.parameter_identifiers()))
            store.insert_parameter(parameter)
            store.set_applicability(parameter.param_id, scope)
            for value, order in options:
                store.insert_option(parameter.param_id, value, order)
            return parameter.param_id

    def update_parameter(
        self, param_id: str, group_id: int | None, param_name: str, param_type: str,
        mandatory: bool = False, alias: str | None = None, applies_to_all: bool | None = None,
        project_type_ids: list[int] | None = None,
    ) -> bool:
        """Guard stored values, then update details and optional scope atomically."""
        parameter = normalize_parameter(SchemaParameter(
            param_id, param_name, param_type, group_id, mandatory, alias,
        ))
        scope = make_applicability(applies_to_all, project_type_ids or []) if applies_to_all is not None else None
        with self._gateway.transaction(write=True) as store:
            previous = store.find_parameter(parameter.param_id)
            if previous is None:
                if scope is not None:
                    raise ValueError("Unknown property")
                return False
            if previous.param_type != parameter.param_type:
                validate_property_type_change(previous.param_type, parameter.param_type,
                                              has_values=store.has_property_values(parameter.param_id))
            updated = store.update_parameter(parameter)
            if scope is not None:
                store.set_applicability(parameter.param_id, scope)
            return updated

    def delete_parameter(self, param_id: str) -> bool:
        """Delete an unused property and its options, preserving referenced data."""
        clean_id = param_id.strip()
        with self._gateway.transaction(write=True) as store:
            validate_property_deletion(has_values=store.has_property_values(clean_id))
            return store.delete_parameter(clean_id)

    def add_option(self, param_id: str, option_value: str, display_order: int) -> int:
        """Create a nonblank choice without changing historical duplicate handling."""
        value, order = normalize_option(option_value, display_order)
        with self._gateway.transaction(write=True) as store:
            return store.insert_option(param_id.strip(), value, order)

    def delete_option(self, option_id: int) -> bool:
        """Reject removal of choices referenced by project values or defaults."""
        with self._gateway.transaction(write=True) as store:
            option = store.find_option(option_id)
            if option is None:
                return False
            validate_option_deletion(is_referenced=store.is_option_referenced(option))
            return store.delete_option(option_id)
