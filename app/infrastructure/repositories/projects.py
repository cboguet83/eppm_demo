"""SQLite adapter for project master data and typed custom values."""

from collections.abc import Collection
from app.domain.access.models import Permission


from app.application.services.business_access import BusinessAccess
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app.application.ports.projects import PlanningProject, ProjectStore
from app.domain.projects.project import Project
from app.domain.projects.links import LinkValues
from app.domain.projects.project_types import TemplateProperty
from app.infrastructure.database.project_transactions import project_connection
from app.infrastructure.database.property_store import effective_template, read_values, write_value


class SqliteProjectStore:
    """Execute operations within the application-owned transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Use an existing connection without committing or closing it."""
        self._connection = connection

    def find(self, project_id: int) -> Project | None:
        """Read all stored values, including inactive ones needed for restoration."""
        row = self._connection.execute(
            "SELECT id,name,status,planned_budget,actual_budget,function_id,project_type_id "
            "FROM project WHERE id=?",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        return Project(
            id=row[0],
            name=row[1],
            status=row[2],
            planned_budget=row[3] or 0.0,
            actual_budget=row[4] or 0.0,
            function_id=row[5],
            project_type_id=row[6],
            dynamic_attributes=read_values(self._connection, owner_id=row[0]).get(row[0], {}),
        )

    def default_type_id(self) -> int:
        """Resolve the configured built-in type inside the write transaction."""
        row = self._connection.execute("SELECT id FROM project_type WHERE is_general=1").fetchone()
        if row is None:
            raise ValueError("The General project type is missing")
        return row[0]

    def template(self, type_id: int) -> list[TemplateProperty]:
        """Load the effective rules from the shared typed-property adapter."""
        return effective_template(self._connection, type_id)

    def choices(self) -> dict[str, set[str]]:
        """Batch allowed options rather than querying once per property."""
        result: dict[str, set[str]] = {}
        for pid, value in self._connection.execute(
            "SELECT param_id,option_value FROM schema_param_options"
        ):
            result.setdefault(pid, set()).add(value)
        return result

    def insert(self, project: Project) -> int:
        """Insert master data and its validated typed values atomically."""
        cursor = self._connection.execute(
            "INSERT INTO main.project(id,name,status,planned_budget,actual_budget,function_id,project_type_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                project.id,
                project.name,
                project.status,
                project.planned_budget,
                project.actual_budget,
                project.function_id,
                project.project_type_id,
            ),
        )
        assert cursor.lastrowid is not None
        for key, value in project.dynamic_attributes.items():
            write_value(self._connection, cursor.lastrowid, key, value)
        return cursor.lastrowid

    def update(self, project: Project) -> None:
        """Upsert active values without deleting stored inactive properties."""
        self._connection.execute(
            "UPDATE main.project SET name=?,status=?,planned_budget=?,actual_budget=?,function_id=?,project_type_id=? WHERE id=?",
            (
                project.name,
                project.status,
                project.planned_budget,
                project.actual_budget,
                project.function_id,
                project.project_type_id,
                project.id,
            ),
        )
        for key, value in project.dynamic_attributes.items():
            write_value(self._connection, project.id, key, value)

    def get_links(self, project_id: int) -> list[LinkValues]:
        """Read custom link values for the atomic project editor."""
        return [LinkValues(url=row[0], alias=row[1]) for row in self._connection.execute(
            "SELECT url,alias FROM project_link WHERE project_id=? ORDER BY id", (project_id,)
        )]

    def replace_links(self, project_id: int, links: list[LinkValues]) -> None:
        """Replace validated custom links within the project save transaction."""
        self._connection.execute("DELETE FROM main.project_link WHERE project_id=?", (project_id,))
        self._connection.executemany("INSERT INTO main.project_link(project_id,url,alias) VALUES(?,?,?)",
                                     [(project_id, link["url"], link["alias"]) for link in links])

    def exists(self, project_id: int) -> bool:
        """Check existence without reading project values."""
        return (
            self._connection.execute("SELECT 1 FROM project WHERE id=?", (project_id,)).fetchone()
            is not None
        )

    def next_id(self) -> int:
        """Respect SQLite's sequence, including IDs belonging to deleted projects."""
        return int(
            self._connection.execute(
                "SELECT MAX(COALESCE((SELECT MAX(id) FROM project),0), "
                "COALESCE((SELECT seq FROM sqlite_sequence WHERE name='project'),0))+1"
            ).fetchone()[0]
        )

    def delete(self, project_id: int) -> bool:
        """Remove task dependencies first and let foreign keys cascade owned rows."""
        self._connection.execute(
            """DELETE FROM main.task_dependencies WHERE predecessor_project_id=?
            OR task_id IN (SELECT id FROM project_task WHERE project_id=?)
            OR predecessor_task_id IN (SELECT id FROM project_task WHERE project_id=?)""",
            (project_id, project_id, project_id),
        )
        self._connection.execute(
            "UPDATE main.project_task SET predecessor_id=NULL WHERE project_id=?", (project_id,)
        )
        self._connection.execute("DELETE FROM main.project_task WHERE project_id=?", (project_id,))
        return (
            self._connection.execute("DELETE FROM main.project WHERE id=?", (project_id,)).rowcount > 0
        )


class SqliteProjectGateway:
    """Supply one closed-after-use connection per project operation."""

    def __init__(self, db_path: str | None = None, *, access: BusinessAccess) -> None:
        """Retain the database identity without opening a connection."""
        self._db_path = db_path
        self.access = access

    @contextmanager
    def transaction(self, *, write: bool = False, permission: Permission | None = None, project_ids: Collection[int] | None = None) -> Iterator[ProjectStore]:
        """Reserve the writer before validation, or provide a consistent read."""
        with project_connection(self._db_path, write=write, access=self.access,
                                permission=permission, project_ids=project_ids) as connection:
            yield SqliteProjectStore(connection)

    def read_planning_catalog(self, property_ids: tuple[str, ...]) -> list[PlanningProject]:
        """Read minimal planning identities and explicitly requested active values."""
        with project_connection(self._db_path, access=self.access) as connection:
            cursor = connection.execute(
                "SELECT p.id,p.name,p.status,p.function_id,p.project_type_id,t.name "
                "FROM project p JOIN project_type t ON t.id=p.project_type_id ORDER BY p.id"
            )
            rows = [
                PlanningProject(
                    id=row[0],
                    name=row[1],
                    status=row[2],
                    function_id=row[3],
                    project_type_id=row[4],
                    project_template=row[5],
                    dynamic_attributes={},
                )
                for row in cursor
            ]
            values = read_values(connection, param_ids=list(property_ids))
            applicability = (
                {
                    tid: {p["param_id"] for p in effective_template(connection, tid)}
                    for tid in {row["project_type_id"] for row in rows}
                }
                if property_ids
                else {}
            )
            for row in rows:
                row["dynamic_attributes"] = {
                    pid: value
                    for pid, value in values.get(row["id"], {}).items()
                    if pid in applicability.get(row["project_type_id"], set())
                }
            return rows
