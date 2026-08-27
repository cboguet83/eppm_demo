"""Repository for Schema Groups, Dynamic Parameters, and Discrete Options."""

import sqlite3
from typing import Optional

import pandas as pd

from src.database.connection import get_db
from src.logging_config import get_logger

logger = get_logger(__name__)


class SchemaRepository:
    """Encapsulates all database operations for schema taxonomy tables."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initializes the SchemaRepository with an optional database path.

        Args:
            db_path: Path to SQLite database. If None, uses configured default.
        """
        self.db_path = db_path

    def get_all_groups(self) -> pd.DataFrame:
        """Loads all schema groups sorted by display order and ID.

        Returns:
            pd.DataFrame: DataFrame containing columns [id, group_name, display_order].
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql("SELECT * FROM schema_groups ORDER BY display_order, id", conn)

    def get_all_parameters(self) -> pd.DataFrame:
        """Loads all schema parameters.

        Returns:
            pd.DataFrame: DataFrame containing [param_id, group_id, param_name, param_type].
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                "SELECT param_id, group_id, param_name, param_type FROM schema_parameters",
                conn,
            )

    def get_all_options(self) -> pd.DataFrame:
        """Loads all discrete options sorted by display order and ID.

        Returns:
            pd.DataFrame: DataFrame containing [id, param_id, option_value, display_order].
        """
        with get_db(self.db_path) as conn:
            return pd.read_sql(
                "SELECT * FROM schema_param_options ORDER BY display_order, id", conn
            )

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
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO schema_groups (group_name, display_order) VALUES (?, ?)",
                (group_name.strip(), display_order),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def update_group(self, group_id: int, group_name: str, display_order: int) -> bool:
        """Updates an existing schema group's name and display order.

        Args:
            group_id: Primary key ID of the group to edit.
            group_name: New name for the group.
            display_order: New display sequence index.

        Returns:
            bool: True if row was updated successfully.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE schema_groups SET group_name = ?, display_order = ? WHERE id = ?",
                (group_name.strip(), display_order, group_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_group(self, group_id: int) -> bool:
        """Deletes a schema group after unassigning parameters referencing it.

        Args:
            group_id: ID of the group to delete.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE schema_parameters SET group_id = NULL WHERE group_id = ?", (group_id,))
            cursor.execute("DELETE FROM schema_groups WHERE id = ?", (group_id,))
            conn.commit()
            return cursor.rowcount > 0

    def create_parameter(
        self,
        param_id: str,
        group_id: Optional[int],
        param_name: str,
        param_type: str,
    ) -> bool:
        """Inserts a new dynamic parameter record.

        Args:
            param_id: Unique parameter ID (e.g. 'PRM_001').
            group_id: Optional parent schema group ID.
            param_name: Parameter label.
            param_type: Data type string.

        Returns:
            bool: True if inserted successfully.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO schema_parameters (param_id, group_id, param_name, param_type) VALUES (?, ?, ?, ?)",
                (param_id.strip(), group_id, param_name.strip(), param_type),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_parameter(self, param_id: str) -> bool:
        """Deletes a parameter and its options.

        Args:
            param_id: Unique ID of the parameter.

        Returns:
            bool: True if deleted.
        """
        clean_id = param_id.strip()
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM schema_param_options WHERE param_id = ?", (clean_id,))
            cursor.execute("DELETE FROM schema_parameters WHERE param_id = ?", (clean_id,))
            conn.commit()
            return cursor.rowcount > 0

    def add_option(self, param_id: str, option_value: str, display_order: int) -> int:
        """Adds a discrete option value for an enum or tags parameter.

        Args:
            param_id: Parent parameter ID.
            option_value: Option string.
            display_order: Display order index.

        Returns:
            int: Newly inserted option ID.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO schema_param_options (param_id, option_value, display_order) VALUES (?, ?, ?)",
                (param_id, option_value.strip(), display_order),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def delete_option(self, option_id: int) -> bool:
        """Deletes a discrete option record by ID.

        Args:
            option_id: Unique numeric option ID.

        Returns:
            bool: True if deleted.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM schema_param_options WHERE id = ?", (option_id,))
            conn.commit()
            return cursor.rowcount > 0
