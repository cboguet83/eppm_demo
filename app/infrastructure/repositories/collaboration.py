"""SQLite collaboration persistence with explicit transaction ownership."""

from collections.abc import Iterator
from contextlib import closing, contextmanager
import logging
import sqlite3

from app.application.exceptions import CollaborationConflictError, CollaborationStorageError
from app.application.ports.collaboration import (
    CatalogEntry,
    FunctionContact,
    ProjectContact,
    ProjectEvent,
)
from app.domain.projects.collaboration import CatalogKind, EventValues
from app.infrastructure.database.connection import get_db

logger = logging.getLogger(__name__)


def _catalog_table(kind: CatalogKind) -> str:
    """Select an allowlisted SQL identifier without interpolating user input."""
    tables = {"role": "project_role", "event_type": "project_event_type"}
    if kind not in tables:
        raise ValueError("Unknown project catalog.")
    return tables[kind]


class SqliteCollaborationStore:
    """Read and mutate collaboration rows on the caller's transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Retain the connection supplied by the transaction gateway."""
        self.connection = connection

    def list_catalog(self, kind: CatalogKind, locale: str) -> list[CatalogEntry]:
        """Read translated labels with their canonical-name fallback."""
        table = _catalog_table(kind)
        rows = self.connection.execute(
            f"""SELECT c.id, c.name, COALESCE(t.label, c.name) AS label
            FROM {table} c LEFT JOIN {table}_translation t
            ON t.catalog_id=c.id AND t.locale=? ORDER BY label COLLATE NOCASE, c.id""",
            (locale,),
        )
        return [CatalogEntry(**dict(row)) for row in rows]

    def save_catalog(self, kind: CatalogKind, name: str, item_id: int | None) -> int:
        """Write the canonical name and English label on the same connection."""
        table = _catalog_table(kind)
        if item_id is None:
            item_id = int(
                self.connection.execute(f"INSERT INTO {table}(name) VALUES (?)", (name,)).lastrowid
            )
        else:
            cursor = self.connection.execute(
                f"UPDATE {table} SET name=? WHERE id=?", (name, item_id)
            )
            if not cursor.rowcount:
                raise ValueError("The catalog entry no longer exists.")
        self.connection.execute(
            f"INSERT INTO {table}_translation VALUES (?, 'en', ?) "
            "ON CONFLICT(catalog_id,locale) DO UPDATE SET label=excluded.label",
            (item_id, name),
        )
        return item_id

    def delete_catalog(self, kind: CatalogKind, item_id: int) -> None:
        """Delete an unused catalog entry; foreign keys protect existing usage."""
        table = _catalog_table(kind)
        self.connection.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))

    def list_functions(self) -> list[FunctionContact]:
        """Resolve current occupants in stable order with vacant-name fallback."""
        rows = self.connection.execute("""SELECT f.function_id, f.name AS function_name,
            COALESCE((SELECT group_concat(full_name, ', ') FROM (
                SELECT trim(e.firstname || ' ' || e.lastname) AS full_name
                FROM employee e WHERE e.function_id=f.function_id
                ORDER BY e.lastname, e.firstname, e.employee_id
            )), f.name) AS person
            FROM function f ORDER BY person COLLATE NOCASE, f.function_id""")
        return [FunctionContact(**dict(row)) for row in rows]

    def list_contacts(self, project_id: int, locale: str) -> list[ProjectContact]:
        """Resolve assignments and occupants in two reads of one snapshot."""
        functions = {row["function_id"]: row for row in self.list_functions()}
        rows = self.connection.execute(
            """SELECT c.id, c.role_id, c.function_id, COALESCE(t.label,r.name) AS role
            FROM project_contact c JOIN project_role r ON r.id=c.role_id
            LEFT JOIN project_role_translation t ON t.catalog_id=r.id AND t.locale=?
            WHERE c.project_id=? ORDER BY COALESCE(t.label,r.name), c.id""",
            (locale, project_id),
        )
        return [ProjectContact(**(dict(row) | functions[row["function_id"]])) for row in rows]

    def save_contact(
        self, project_id: int, role_id: int, function_id: int, contact_id: int | None
    ) -> int:
        """Write an assignment while retaining project ownership and FK checks."""
        if contact_id is None:
            return int(
                self.connection.execute(
                    "INSERT INTO project_contact(project_id,role_id,function_id) "
                    "VALUES (?,?,?)",
                    (project_id, role_id, function_id),
                ).lastrowid
            )
        cursor = self.connection.execute(
            "UPDATE project_contact SET role_id=?, function_id=? WHERE id=? AND project_id=?",
            (role_id, function_id, contact_id, project_id),
        )
        if not cursor.rowcount:
            raise ValueError("The contact no longer exists in this project.")
        return contact_id

    def delete_contact(self, project_id: int, contact_id: int) -> None:
        """Delete only the matching project's assignment, preserving no-op deletes."""
        self.connection.execute(
            "DELETE FROM project_contact WHERE id=? AND project_id=?", (contact_id, project_id)
        )

    def list_events(
        self, project_id: int, locale: str, *, offset: int, limit: int
    ) -> list[ProjectEvent]:
        """Read an explicitly projected, newest-first page of project events."""
        rows = self.connection.execute(
            """SELECT e.id,e.project_id,e.title,e.description,e.deadline,
            e.scope,e.comment,e.event_type_id,e.status,e.created_at,e.updated_at,
            COALESCE(t.label,c.name) AS event_type
            FROM project_log_event e JOIN project_event_type c ON c.id=e.event_type_id
            LEFT JOIN project_event_type_translation t ON t.catalog_id=c.id AND t.locale=?
            WHERE e.project_id=? ORDER BY e.id DESC LIMIT ? OFFSET ?""",
            (locale, project_id, limit, offset),
        )
        return [ProjectEvent(**dict(row)) for row in rows]

    def save_event(self, project_id: int, values: EventValues, event_id: int | None) -> int:
        """Persist validated fields and scope updates to the owning project."""
        parameters = tuple(
            values[key]
            for key in (
                "title",
                "description",
                "deadline",
                "scope",
                "comment",
                "event_type_id",
                "status",
            )
        )
        if event_id is None:
            return int(
                self.connection.execute(
                    """INSERT INTO project_log_event
                (title,description,deadline,scope,comment,event_type_id,status,project_id)
                VALUES (?,?,?,?,?,?,?,?)""",
                    (*parameters, project_id),
                ).lastrowid
            )
        cursor = self.connection.execute(
            """UPDATE project_log_event SET title=?,description=?,deadline=?,scope=?,
            comment=?,event_type_id=?,status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND project_id=?""",
            (*parameters, event_id, project_id),
        )
        if not cursor.rowcount:
            raise ValueError("The event no longer exists in this project.")
        return event_id


class SqliteCollaborationGateway:
    """Own connections, transaction completion, and safe storage errors."""

    def __init__(self, db_path: str | None = None) -> None:
        """Retain the configured database path without opening a connection."""
        self.db_path = db_path

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[SqliteCollaborationStore]:
        """Read one snapshot or commit all writes atomically, closing on every exit."""
        try:
            with closing(get_db(self.db_path)) as connection:
                connection.row_factory = sqlite3.Row
                with connection:
                    connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                    yield SqliteCollaborationStore(connection)
        except sqlite3.IntegrityError as exc:
            raise CollaborationConflictError(
                "Cannot save: this entry is duplicated, missing, or still in use."
            ) from exc
        except sqlite3.DatabaseError as exc:
            logger.error("Collaboration storage operation failed (%s)", type(exc).__name__)
            raise CollaborationStorageError(
                "Collaboration data could not be accessed. Please try again."
            ) from exc
