"""SQLite persistence for project-schema administration."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager

from app.application.exceptions import SchemaConflictError, SchemaStorageError
from app.application.ports.schema import SchemaStore
from app.domain.projects.project_types import PropertyApplicability
from app.domain.projects.schema import SchemaGroup, SchemaParameter, SchemaParamOption
from app.infrastructure.database.connection import get_db
from app.infrastructure.repositories.project_types import SqliteProjectTypeStore
from app.shared.logging import get_logger

logger = get_logger(__name__)


class SqliteSchemaStore:
    """Execute schema operations on a connection owned by the application scope."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Retain the caller's connection without committing or closing it."""
        self._connection = connection

    def groups(self) -> list[SchemaGroup]:
        """Read groups in the editor's established order."""
        return [
            SchemaGroup(*row)
            for row in self._connection.execute(
                "SELECT group_name,display_order,id FROM schema_groups ORDER BY display_order,id"
            )
        ]

    def parameters(self) -> list[SchemaParameter]:
        """Read typed property definitions in their existing storage order."""
        return [
            SchemaParameter(*row[:4], bool(row[4]), row[5], bool(row[6]))
            for row in self._connection.execute(
                "SELECT param_id,param_name,param_type,group_id,mandatory,alias,applies_to_all FROM schema_parameters"
            )
        ]

    def options(self) -> list[SchemaParamOption]:
        """Read discrete choices in display order."""
        return [
            SchemaParamOption(*row)
            for row in self._connection.execute(
                "SELECT param_id,option_value,display_order,id FROM schema_param_options ORDER BY display_order,id"
            )
        ]

    def parameter_identifiers(self) -> list[str]:
        """Read property identities from the initialized schema."""
        return [
            row[0] for row in self._connection.execute("SELECT param_id FROM schema_parameters")
        ]

    def find_parameter(self, param_id: str) -> SchemaParameter | None:
        """Read one definition for a guarded edit."""
        row = self._connection.execute(
            "SELECT param_id,param_name,param_type,group_id,mandatory,alias,applies_to_all "
            "FROM schema_parameters WHERE param_id=?",
            (param_id,),
        ).fetchone()
        return SchemaParameter(*row[:4], bool(row[4]), row[5], bool(row[6])) if row else None

    def find_option(self, option_id: int) -> SchemaParamOption | None:
        """Read a choice for its reference check."""
        row = self._connection.execute(
            "SELECT param_id,option_value,display_order,id FROM schema_param_options WHERE id=?",
            (option_id,),
        ).fetchone()
        return SchemaParamOption(*row) if row else None

    def has_property_values(self, param_id: str) -> bool:
        """Include all project/default rows, including explicitly cleared values."""
        return any(
            self._connection.execute(
                f"SELECT 1 FROM {table} WHERE param_id=? LIMIT 1",
                (param_id,),
            ).fetchone()
            for table in ("project_property_value", "project_type_property_default")
        )

    def is_option_referenced(self, option: SchemaParamOption) -> bool:
        """Check scalar and list values in projects and template defaults."""
        for table in ("project_property_value", "project_type_property_default"):
            for suffix, column in (("", "text_value"), ("_item", "value")):
                if self._connection.execute(
                    f"SELECT 1 FROM {table}{suffix} WHERE param_id=? AND {column}=? LIMIT 1",
                    (option.param_id, option.option_value),
                ).fetchone():
                    return True
        return False

    def insert_group(self, group_name: str, display_order: int) -> int:
        """Persist normalized group details; unique constraints stay authoritative."""
        cursor = self._connection.execute(
            "INSERT INTO schema_groups(group_name,display_order) VALUES (?,?)",
            (group_name, display_order),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def update_group(self, group_id: int, group_name: str, display_order: int) -> bool:
        """Persist normalized group details in the caller's transaction."""
        return (
            self._connection.execute(
                "UPDATE schema_groups SET group_name=?,display_order=? WHERE id=?",
                (group_name, display_order, group_id),
            ).rowcount
            > 0
        )

    def ungroup_parameters(self, group_id: int) -> None:
        """Detach properties without deleting them or their values."""
        self._connection.execute(
            "UPDATE schema_parameters SET group_id=NULL WHERE group_id=?", (group_id,)
        )

    def delete_group(self, group_id: int) -> bool:
        """Delete a group after the application has detached its properties."""
        return (
            self._connection.execute("DELETE FROM schema_groups WHERE id=?", (group_id,)).rowcount
            > 0
        )

    def insert_parameter(self, parameter: SchemaParameter) -> None:
        """Insert details before applying selected-type membership on this connection."""
        self._connection.execute(
            "INSERT INTO schema_parameters(param_id,group_id,param_name,param_type,mandatory,alias) VALUES (?,?,?,?,?,?)",
            (
                parameter.param_id,
                parameter.group_id,
                parameter.param_name,
                parameter.param_type,
                int(parameter.mandatory),
                parameter.alias,
            ),
        )

    def update_parameter(self, parameter: SchemaParameter) -> bool:
        """Update details without implicitly changing applicability."""
        return (
            self._connection.execute(
                "UPDATE schema_parameters SET group_id=?,param_name=?,param_type=?,mandatory=?,alias=? WHERE param_id=?",
                (
                    parameter.group_id,
                    parameter.param_name,
                    parameter.param_type,
                    int(parameter.mandatory),
                    parameter.alias,
                    parameter.param_id,
                ),
            ).rowcount
            > 0
        )

    def set_applicability(self, param_id: str, scope: PropertyApplicability) -> None:
        """Reuse the migrated membership adapter on the same transaction."""
        SqliteProjectTypeStore(self._connection).set_applicability(param_id, scope)

    def delete_parameter(self, param_id: str) -> bool:
        """Delete unused options and the guarded property as one unit."""
        self._connection.execute("DELETE FROM schema_param_options WHERE param_id=?", (param_id,))
        return (
            self._connection.execute(
                "DELETE FROM schema_parameters WHERE param_id=?", (param_id,)
            ).rowcount
            > 0
        )

    def insert_option(self, param_id: str, option_value: str, display_order: int) -> int:
        """Insert one ordered choice without committing the outer operation."""
        cursor = self._connection.execute(
            "INSERT INTO schema_param_options(param_id,option_value,display_order) VALUES (?,?,?)",
            (param_id, option_value, display_order),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def delete_option(self, option_id: int) -> bool:
        """Delete a choice after the application reference guard."""
        return (
            self._connection.execute(
                "DELETE FROM schema_param_options WHERE id=?", (option_id,)
            ).rowcount
            > 0
        )


class SqliteSchemaGateway:
    """Provide consistent reads, guarded writes, and safe schema error messages."""

    def __init__(self, db_path: str | None = None) -> None:
        """Store the database identity without opening a connection."""
        self._db_path = db_path

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[SchemaStore]:
        """Reserve writes before guards, commit or roll back, and always close."""
        try:
            with closing(get_db(self._db_path)) as connection:
                with connection:
                    connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                    yield SqliteSchemaStore(connection)
        except sqlite3.IntegrityError as exc:
            messages = {
                "schema_groups.group_name": "A group with this name already exists.",
                "schema_groups.display_order": "This group display order is already in use.",
                "schema_parameters.param_id": "A property with this ID already exists.",
            }
            message = next(
                (text for constraint, text in messages.items() if constraint in str(exc)),
                "The schema change conflicts with an existing reference or constraint.",
            )
            raise SchemaConflictError(message) from exc
        except sqlite3.DatabaseError as exc:
            logger.error("Schema storage operation failed (%s)", type(exc).__name__)
            raise SchemaStorageError(
                "Schema data could not be accessed. Please try again."
            ) from exc
