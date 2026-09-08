"""Persistence and validation for project responsibility assignments and logs."""

from contextlib import closing
from datetime import date
from typing import Literal

from src.database.connection import get_db

CatalogKind = Literal["role", "event_type"]
EVENT_STATUSES = ("new", "active", "completed", "cancelled", "rejected", "closed")
EVENT_SCOPES = ("internal", "global")


def _catalog_table(kind: CatalogKind) -> str:
    if kind not in ("role", "event_type"):
        raise ValueError("Unknown project catalog.")
    return "project_" + kind


def _required_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required.")
    return value.strip()


class ProjectCollaborationRepository:
    """Manage contacts, reference catalogs and project-scoped event records."""

    def __init__(self, db_path: str | None = None) -> None:
        """Use the supplied SQLite database, or the configured application DB."""
        self.db_path = db_path

    def list_catalog(self, kind: CatalogKind, locale: str = "en") -> list[dict]:
        """Return localized catalog labels with their canonical-name fallback."""
        table = _catalog_table(kind)
        with closing(get_db(self.db_path)) as conn:
            rows = conn.execute(f"""SELECT c.id, c.name, COALESCE(t.label, c.name) AS label
                FROM {table} c LEFT JOIN {table}_translation t
                ON t.catalog_id=c.id AND t.locale=? ORDER BY label COLLATE NOCASE, c.id""", (locale,))
            return [dict(zip(("id", "name", "label"), row)) for row in rows]

    def save_catalog(self, kind: CatalogKind, name: str, item_id: int | None = None) -> int:
        """Create or rename a role/type; retain all assignments using its ID."""
        table = _catalog_table(kind)
        name = _required_text(name, "Name")
        with closing(get_db(self.db_path)) as conn, conn:
            if item_id is None:
                item_id = int(conn.execute(f"INSERT INTO {table}(name) VALUES (?)", (name,)).lastrowid)
            else:
                cursor = conn.execute(f"UPDATE {table} SET name=? WHERE id=?", (name, item_id))
                if not cursor.rowcount:
                    raise ValueError("The catalog entry no longer exists.")
            conn.execute(f"INSERT INTO {table}_translation VALUES (?, 'en', ?) "
                         "ON CONFLICT(catalog_id,locale) DO UPDATE SET label=excluded.label", (item_id, name))
            return item_id

    def delete_catalog(self, kind: CatalogKind, item_id: int) -> None:
        """Delete an unused catalog entry; foreign keys protect existing usage."""
        table = _catalog_table(kind)
        with closing(get_db(self.db_path)) as conn, conn:
            conn.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))

    def list_functions(self) -> list[dict]:
        """Return functions with current occupants first and vacant-name fallback.

        Multiple occupants are displayed together; assignments always reference
        the function, so a staff change automatically updates the displayed name.
        """
        with closing(get_db(self.db_path)) as conn:
            rows = conn.execute("""SELECT f.function_id, f.name,
                COALESCE((SELECT group_concat(full_name, ', ') FROM (
                    SELECT trim(e.firstname || ' ' || e.lastname) AS full_name
                    FROM employee e WHERE e.function_id=f.function_id
                    ORDER BY e.lastname, e.firstname, e.employee_id
                )), f.name) AS person
                FROM function f ORDER BY person COLLATE NOCASE, f.function_id""")
            return [dict(zip(("function_id", "function_name", "person"), row)) for row in rows]

    def list_contacts(self, project_id: int, locale: str = "en") -> list[dict]:
        """List a project's roles and resolve occupants in a bounded pair of reads."""
        functions = {row["function_id"]: row for row in self.list_functions()}
        with closing(get_db(self.db_path)) as conn:
            rows = conn.execute("""SELECT c.id, c.role_id, c.function_id, COALESCE(t.label,r.name)
                FROM project_contact c JOIN project_role r ON r.id=c.role_id
                LEFT JOIN project_role_translation t ON t.catalog_id=r.id AND t.locale=?
                WHERE c.project_id=? ORDER BY COALESCE(t.label,r.name), c.id""", (locale, project_id))
            return [{**dict(zip(("id", "role_id", "function_id", "role"), row)),
                     **functions[row[2]]} for row in rows]

    def save_contact(self, project_id: int, role_id: int, function_id: int,
                     contact_id: int | None = None) -> int:
        """Assign a role to a function; reject duplicate triples or missing FKs."""
        with closing(get_db(self.db_path)) as conn, conn:
            if contact_id is None:
                return int(conn.execute("INSERT INTO project_contact(project_id,role_id,function_id) "
                                        "VALUES (?,?,?)", (project_id, role_id, function_id)).lastrowid)
            cursor = conn.execute("UPDATE project_contact SET role_id=?, function_id=? WHERE id=? AND project_id=?",
                                  (role_id, function_id, contact_id, project_id))
            if not cursor.rowcount:
                raise ValueError("The contact no longer exists in this project.")
            return contact_id

    def delete_contact(self, project_id: int, contact_id: int) -> None:
        """Remove only the specified project's contact assignment."""
        with closing(get_db(self.db_path)) as conn, conn:
            conn.execute("DELETE FROM project_contact WHERE id=? AND project_id=?", (contact_id, project_id))

    def list_events(self, project_id: int, locale: str = "en", *, offset: int = 0,
                    limit: int = 50) -> list[dict]:
        """Return a bounded newest-first log page, including localized type names."""
        with closing(get_db(self.db_path)) as conn:
            cursor = conn.execute("""SELECT e.*, COALESCE(t.label,c.name) AS event_type
                FROM project_log_event e JOIN project_event_type c ON c.id=e.event_type_id
                LEFT JOIN project_event_type_translation t ON t.catalog_id=c.id AND t.locale=?
                WHERE e.project_id=? ORDER BY e.id DESC LIMIT ? OFFSET ?""",
                                  (locale, project_id, min(100, max(1, limit)), max(0, offset)))
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor]

    def save_event(self, project_id: int, *, title: str, description: str,
                   deadline: str | None, scope: str, comment: str, event_type_id: int,
                   status: str = "new", event_id: int | None = None) -> int:
        """Validate and persist an event; updates cannot cross project boundaries."""
        title = _required_text(title, "Title")
        if scope not in EVENT_SCOPES or status not in EVENT_STATUSES:
            raise ValueError("Invalid event scope or state.")
        if deadline is not None:
            deadline = date.fromisoformat(deadline).isoformat()
        values = (title, description, deadline, scope, comment, event_type_id, status)
        with closing(get_db(self.db_path)) as conn, conn:
            if event_id is None:
                return int(conn.execute("""INSERT INTO project_log_event
                    (title,description,deadline,scope,comment,event_type_id,status,project_id)
                    VALUES (?,?,?,?,?,?,?,?)""", (*values, project_id)).lastrowid)
            cursor = conn.execute("""UPDATE project_log_event SET title=?,description=?,deadline=?,scope=?,
                comment=?,event_type_id=?,status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND project_id=?""",
                                  (*values, event_id, project_id))
            if not cursor.rowcount:
                raise ValueError("The event no longer exists in this project.")
            return event_id
