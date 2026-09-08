"""Compatibility facade for schema groups, properties, and discrete choices."""

from dataclasses import asdict

import pandas as pd

from app.main import create_schema_service
from src.repositories.schema_errors import legacy_schema_errors


class SchemaRepository:
    """Keep legacy frames, return values, and SQLite errors outside the new core."""

    def __init__(self, db_path: str | None = None) -> None:
        """Initializes the SchemaRepository with an optional database path.

        Args:
            db_path: Path to SQLite database. If None, uses configured default.
        """
        self.db_path = db_path
        self.service = create_schema_service(db_path)

    def get_all_groups(self) -> pd.DataFrame:
        """Loads all schema groups sorted by display order and ID.

        Returns:
            pd.DataFrame: DataFrame containing columns [id, group_name, display_order].
        """
        with legacy_schema_errors():
            return pd.DataFrame([asdict(group) for group in self.service.get_all_groups()],
                                columns=["id", "group_name", "display_order"])

    def get_all_parameters(self) -> pd.DataFrame:
        """Loads all schema parameters.

        Returns:
            pd.DataFrame: DataFrame containing [param_id, group_id, param_name, param_type, mandatory, alias].
        """
        with legacy_schema_errors():
            return pd.DataFrame([
                {**asdict(param), "mandatory": int(param.mandatory), "applies_to_all": int(param.applies_to_all)}
                for param in self.service.get_all_parameters()
            ], columns=["param_id", "group_id", "param_name", "param_type", "mandatory", "alias", "applies_to_all"])

    def get_all_options(self) -> pd.DataFrame:
        """Loads all discrete options sorted by display order and ID.

        Returns:
            pd.DataFrame: DataFrame containing [id, param_id, option_value, display_order].
        """
        with legacy_schema_errors():
            return pd.DataFrame([asdict(option) for option in self.service.get_all_options()],
                                columns=["id", "param_id", "option_value", "display_order"])

    def create_group(self, group_name: str, display_order: int) -> int:
        """Creates a new schema group.

        Args:
            group_name: Unique name of the group.
            display_order: Sequence order index.

        Returns:
            int: Newly inserted group ID.

        Raises:
            sqlite3.IntegrityError: If group name or display order is not unique.
        """
        with legacy_schema_errors():
            return self.service.create_group(group_name, display_order)

    def update_group(self, group_id: int, group_name: str, display_order: int) -> bool:
        """Updates an existing schema group's name and display order.

        Args:
            group_id: Primary key ID of the group to edit.
            group_name: New name for the group.
            display_order: New display sequence index.

        Returns:
            bool: True if row was updated successfully.
        """
        with legacy_schema_errors():
            return self.service.update_group(group_id, group_name, display_order)

    def delete_group(self, group_id: int) -> bool:
        """Deletes a schema group after unassigning parameters referencing it.

        Args:
            group_id: ID of the group to delete.

        Returns:
            bool: True if deleted.
        """
        with legacy_schema_errors():
            return self.service.delete_group(group_id)

    def create_parameter(
        self,
        param_id: str,
        group_id: int | None,
        param_name: str,
        param_type: str,
        mandatory: bool = False,
        alias: str | None = None,
        applies_to_all: bool = True,
        project_type_ids: list[int] | None = None,
    ) -> bool:
        """Inserts a new dynamic parameter record.

        Args:
            param_id: Unique parameter ID (e.g. 'PRM_001').
            group_id: Optional parent schema group ID.
            param_name: Parameter label.
            param_type: Data type string.
            mandatory: Whether this parameter is required to save a project.
            alias: Optional alternative name or display alias.

        Returns:
            bool: True if inserted successfully.
        """
        with legacy_schema_errors():
            return bool(self.service.create_parameter(param_id, group_id, param_name, param_type,
                                                     mandatory, alias, applies_to_all, project_type_ids))

    def update_parameter(
        self,
        param_id: str,
        group_id: int | None,
        param_name: str,
        param_type: str,
        mandatory: bool = False,
        alias: str | None = None,
        applies_to_all: bool | None = None,
        project_type_ids: list[int] | None = None,
    ) -> bool:
        """Updates an existing dynamic parameter definition.

        Args:
            param_id: Unique parameter ID.
            group_id: Optional parent schema group ID.
            param_name: Updated parameter label.
            param_type: Updated data type string.
            mandatory: Whether the parameter is mandatory.
            alias: Optional parameter alias.

        Returns:
            bool: True if updated.
        """
        with legacy_schema_errors():
            return self.service.update_parameter(param_id, group_id, param_name, param_type,
                                                 mandatory, alias, applies_to_all, project_type_ids)

    def delete_parameter(self, param_id: str) -> bool:
        """Deletes a parameter and its options.

        Args:
            param_id: Unique ID of the parameter.

        Returns:
            bool: True if deleted.
        """
        with legacy_schema_errors():
            return self.service.delete_parameter(param_id)

    def add_option(self, param_id: str, option_value: str, display_order: int) -> int:
        """Adds a discrete option value for an enum or tags parameter.

        Args:
            param_id: Parent parameter ID.
            option_value: Option string.
            display_order: Display order index.

        Returns:
            int: Newly inserted option ID.
        """
        with legacy_schema_errors():
            return self.service.add_option(param_id, option_value, display_order)

    def delete_option(self, option_id: int) -> bool:
        """Deletes a discrete option record by ID.

        Args:
            option_id: Unique numeric option ID.

        Returns:
            bool: True if deleted.
        """
        with legacy_schema_errors():
            return self.service.delete_option(option_id)
