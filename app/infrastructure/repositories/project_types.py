"""SQLite project-type storage, with explicit transaction and error boundaries."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from typing import cast

from app.application.exceptions import ProjectTypeConflictError, ProjectTypeStorageError
from app.application.ports.project_types import ProjectTypeStore
from app.domain.projects.project_types import (
    ProjectType, PropertyApplicability, PropertyDefinition, PropertyValue,
)
from app.infrastructure.database.connection import get_db
from app.shared.logging import get_logger

from app.infrastructure.database.property_store import parameters, read_values, write_value

logger = get_logger(__name__)


class SqliteProjectTypeStore:
    """Execute persistence operations on a caller-owned SQLite connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Use the supplied connection without committing or closing it."""
        self._connection = connection

    def list_types(self) -> list[ProjectType]:
        """Load types with the built-in type first and the rest by name."""
        rows = self._connection.execute(
            "SELECT id, name, description, is_general FROM project_type "
            "ORDER BY is_general DESC, name"
        )
        return [ProjectType(row[0], row[1], row[2], bool(row[3])) for row in rows]

    def find_type(self, type_id: int) -> ProjectType | None:
        """Load one type, or None if it does not exist."""
        row = self._connection.execute(
            "SELECT id, name, description, is_general FROM project_type WHERE id=?",
            (type_id,),
        ).fetchone()
        return ProjectType(row[0], row[1], row[2], bool(row[3])) if row else None

    def insert_type(self, name: str, description: str) -> int:
        """Insert normalized details; database constraints remain authoritative."""
        cursor = self._connection.execute(
            "INSERT INTO project_type(name, description) VALUES (?, ?)", (name, description),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def update_type(self, type_id: int, name: str, description: str) -> None:
        """Persist validated details in the current transaction."""
        self._connection.execute(
            "UPDATE project_type SET name=?, description=? WHERE id=?",
            (name, description, type_id),
        )

    def delete_type(self, type_id: int) -> None:
        """Delete a type after the application's reference checks."""
        self._connection.execute("DELETE FROM project_type WHERE id=?", (type_id,))

    def has_projects(self, type_id: int) -> bool:
        """Check for projects that still reference this type."""
        return self._connection.execute(
            "SELECT 1 FROM project WHERE project_type_id=? LIMIT 1", (type_id,),
        ).fetchone() is not None

    def has_exclusive_properties(self, type_id: int) -> bool:
        """Check whether deletion would orphan a selected-only property."""
        return self._connection.execute(
            """SELECT 1 FROM project_type_property m
            JOIN schema_parameters p USING(param_id)
            WHERE m.project_type_id=? AND p.applies_to_all=0 AND NOT EXISTS
                (SELECT 1 FROM project_type_property other
                 WHERE other.param_id=m.param_id AND other.project_type_id<>?)
            LIMIT 1""", (type_id, type_id),
        ).fetchone() is not None

    def property_definitions(self) -> list[PropertyDefinition]:
        """Adapt the shared schema store to the application's typed contract."""
        return cast(list[PropertyDefinition], parameters(self._connection))

    def selected_properties(self, type_id: int) -> set[str]:
        """Load explicitly applicable property IDs."""
        return {row[0] for row in self._connection.execute(
            "SELECT param_id FROM project_type_property WHERE project_type_id=?", (type_id,),
        )}

    def required_overrides(self, type_id: int) -> dict[str, bool | int | None]:
        """Load the nullable required-setting overrides."""
        return dict(self._connection.execute(
            "SELECT param_id, mandatory_override FROM project_type_property_rule "
            "WHERE project_type_id=?", (type_id,),
        ))

    def defaults(self, type_id: int) -> dict[str, PropertyValue]:
        """Read defaults through the shared relational property-value adapter."""
        return read_values(self._connection, defaults=True, owner_id=type_id).get(type_id, {})

    def get_applicability(self, param_id: str) -> PropertyApplicability | None:
        """Load all-types scope and selected membership for a known property."""
        row = self._connection.execute(
            "SELECT applies_to_all FROM schema_parameters WHERE param_id=?", (param_id,),
        ).fetchone()
        if row is None:
            return None
        ids = tuple(row[0] for row in self._connection.execute(
            "SELECT project_type_id FROM project_type_property "
            "WHERE param_id=? ORDER BY project_type_id", (param_id,),
        ))
        return PropertyApplicability(bool(row[0]), ids)

    def set_applicability(self, param_id: str, scope: PropertyApplicability) -> None:
        """Replace membership without committing the caller's transaction."""
        updated = self._connection.execute(
            "UPDATE schema_parameters SET applies_to_all=? WHERE param_id=?",
            (int(scope.applies_to_all), param_id),
        )
        if not updated.rowcount:
            raise ValueError("Unknown property")
        self._connection.execute("DELETE FROM project_type_property WHERE param_id=?", (param_id,))
        self._connection.executemany(
            "INSERT INTO project_type_property(project_type_id,param_id) VALUES (?,?)",
            [(type_id, param_id) for type_id in scope.type_ids],
        )

    def save_rule(
        self, type_id: int, param_id: str, mandatory_override: bool | None,
        *, has_default: bool, default_value: PropertyValue,
    ) -> None:
        """Persist the override and typed default on the same connection."""
        self._connection.execute(
            """INSERT INTO project_type_property_rule
            (project_type_id,param_id,mandatory_override) VALUES (?,?,?)
            ON CONFLICT(project_type_id,param_id) DO UPDATE
            SET mandatory_override=excluded.mandatory_override""",
            (type_id, param_id, mandatory_override),
        )
        if has_default:
            write_value(self._connection, type_id, param_id, default_value, defaults=True)
        else:
            self._connection.execute(
                "DELETE FROM project_type_property_default WHERE project_type_id=? AND param_id=?",
                (type_id, param_id),
            )


class SqliteProjectTypeGateway:
    """Open, commit/roll back, and close one connection per application operation."""

    def __init__(self, db_path: str | None = None) -> None:
        """Retain the configured path; no connection is opened at construction."""
        self._db_path = db_path

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[ProjectTypeStore]:
        """Hold a consistent snapshot and protect write guards from races.

        A write reserves SQLite's writer lock before reading deletion/rename
        guards. Any failure, including invalid defaults, rolls back the entire
        operation. SQLite exceptions are translated at this boundary.
        """
        try:
            with closing(get_db(self._db_path)) as connection:
                with connection:
                    connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                    yield SqliteProjectTypeStore(connection)
        except sqlite3.IntegrityError as exc:
            if "project_type.name" in str(exc):
                message = "A project type with this name already exists"
            else:
                message = "The change conflicts with an existing reference or property constraint"
            raise ProjectTypeConflictError(message) from exc
        except sqlite3.DatabaseError as exc:
            logger.error("Project-type storage operation failed (%s)", type(exc).__name__)
            raise ProjectTypeStorageError("Project-type data could not be accessed. Please try again.") from exc
