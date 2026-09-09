"""SQLite transaction guards and scoped read views for existing business repositories."""

from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
import json
import sqlite3

from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, DeploymentActor, Permission
from app.infrastructure.repositories.access import SqliteAccessStore


_OWNED_TABLES = {
    "project_link": "project_id", "project_contact": "project_id", "project_log_event": "project_id",
    "project_property_value": "project_id", "project_property_value_item": "project_id",
    "project_tag": "project_id", "task_tag": "task_id",
}
_SHARED_TABLES = frozenset({
    "schema_groups", "schema_parameters", "schema_param_options", "schema_parameter_translation",
    "project_type", "project_type_property", "project_type_property_rule", "project_type_property_default",
    "project_type_property_default_item", "function_type", "function", "team", "employee",
    "employee_calendar_exception", "team_function", "resource_pool", "resource_pool_mapping",
    "resource_pool_tag", "resource_pool_group", "resource_pool_group_member", "tag_group", "tag_dictionnary",
    "project_role", "project_role_translation", "project_event_type", "project_event_type_translation",
})
_GUARDED_TABLES = frozenset(_OWNED_TABLES) | _SHARED_TABLES | {
    "project", "project_task", "task_dependencies", "resource_pool_assignment",
}
_PROTECTED_DEFINITIONS = frozenset({
    "schema_parameters", "schema_param_options", "project_type", "project_type_property",
    "project_type_property_rule", "project_type_property_default", "project_type_property_default_item",
})


@contextmanager
def authorized_business_transaction(
    connection: sqlite3.Connection, access: BusinessAccess, *,
    permission: Permission | None = None, project_ids: Collection[int] | None = None,
) -> Iterator[None]:
    """Install enforcement and translate trigger denials before normal adapter errors."""
    security = SqliteBusinessSecurity(connection, access)
    if permission is not None:
        access.require(security.store, permission, project_ids)
    security.install()
    try:
        yield
    except sqlite3.Error:
        if security.denial is not None:
            raise security.denial from None
        raise


class SqliteBusinessSecurity:
    """Attach current-actor enforcement to one caller-owned database transaction.

    Temporary read views preserve existing joins while applying project visibility
    before aggregates and pages. Business writes address ``main.<table>`` explicitly;
    temporary BEFORE triggers reauthorize persisted OLD/NEW owners in that same
    transaction. Existing database triggers and constraints still execute normally.
    """

    def __init__(self, connection: sqlite3.Connection, access: BusinessAccess) -> None:
        self.connection, self.access = connection, access
        self.store = SqliteAccessStore(connection)
        self.denial: AccessDenied | None = None
        self.deleted_task_owners: dict[int, int] = {}
        self.primary_keys: dict[str, tuple[str, ...]] = {}
        self.replaced_rows: dict[tuple[str, tuple[object, ...]], dict[str, object]] = {}

    def install(self) -> None:
        """Install isolated views and write guards only after a snapshot/writer begins."""
        if not self.connection.in_transaction:
            raise ValueError("Business authorization requires a caller-owned transaction.")
        allowed = self.access.projects(self.store)
        self.connection.execute("CREATE TEMP TABLE eppm_visible_project(id INTEGER PRIMARY KEY)")
        self.connection.executemany("INSERT INTO eppm_visible_project(id) VALUES(?)", [(item,) for item in allowed])
        self._read_views()
        self.connection.create_function("eppm_authorize_write", 4, self._authorize)
        self.connection.create_function("eppm_audit_write", 4, self._audit)
        existing = {row[0] for row in self.connection.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
        for table in sorted(_GUARDED_TABLES & existing):
            schema = self.connection.execute(f'PRAGMA main.table_info("{table}")').fetchall()
            columns = [row[1] for row in schema]
            self.primary_keys[table] = tuple(row[1] for row in sorted(schema, key=lambda item: item[5]) if row[5])
            for operation in ("INSERT", "UPDATE", "DELETE"):
                old = self._row_json(columns, "OLD") if operation != "INSERT" else "'{}'"
                new = self._row_json(columns, "NEW") if operation != "DELETE" else "'{}'"
                self.connection.execute(f"""CREATE TEMP TRIGGER eppm_guard_{table}_{operation}
                    BEFORE {operation} ON main.{table}
                    BEGIN SELECT CASE WHEN eppm_authorize_write('{table}','{operation}',{old},{new})!=1
                        THEN RAISE(ABORT,'Application access denied') END; END""")
                if table in _PROTECTED_DEFINITIONS or table in {"project", "project_property_value", "project_property_value_item"}:
                    self.connection.execute(f"""CREATE TEMP TRIGGER eppm_audit_{table}_{operation}
                        AFTER {operation} ON main.{table}
                        BEGIN SELECT eppm_audit_write('{table}','{operation}',{old},{new}); END""")

    @staticmethod
    def _row_json(columns: list[str], prefix: str) -> str:
        # Identifiers originate only from the fixed table allowlist and trusted schema.
        return "json_object(" + ",".join(f"'{name}',{prefix}.\"{name}\"" for name in columns) + ")"

    def _read_views(self) -> None:
        visible = "SELECT id FROM temp.eppm_visible_project"
        predicates = {"project": f"id IN ({visible})", "project_task": f"project_id IN ({visible})"}
        for table, owner in _OWNED_TABLES.items():
            predicates[table] = (f"task_id IN (SELECT id FROM main.project_task WHERE project_id IN ({visible}))"
                                 if owner == "task_id" else f"project_id IN ({visible})")
        predicates["resource_pool_assignment"] = f"""project_id IN ({visible}) AND
            (task_id IS NULL OR task_id IN (SELECT id FROM main.project_task WHERE project_id IN ({visible})))"""
        predicates["task_dependencies"] = f"""task_id IN (SELECT id FROM main.project_task WHERE project_id IN ({visible}))
            AND (predecessor_project_id IS NULL OR predecessor_project_id IN ({visible}))
            AND (predecessor_task_id IS NULL OR predecessor_task_id IN
                (SELECT id FROM main.project_task WHERE project_id IN ({visible})))"""
        for table, predicate in predicates.items():
            if table == "project_task":
                columns = [row[1] for row in self.connection.execute("PRAGMA main.table_info(project_task)")]
                fields = [f'"{name}"' for name in columns if name != "predecessor_id"]
                fields.append(f"CASE WHEN predecessor_id IN (SELECT id FROM main.project_task WHERE project_id IN ({visible})) "
                              "THEN predecessor_id ELSE NULL END AS predecessor_id")
                selection = ",".join(fields)
            else:
                selection = "*"
            self.connection.execute(f"CREATE TEMP VIEW {table} AS SELECT {selection} FROM main.{table} WHERE {predicate}")
        if not self.access.global_permission(self.store, Permission.READ):
            # Shared violation flags can reflect hidden predecessor projects. Scoped
            # readers compute their summaries from the visible relations only.
            self.connection.execute("""CREATE TEMP TABLE planning_summary_cache (
                project_id INTEGER PRIMARY KEY, name TEXT,start TEXT,end TEXT,
                task_count INTEGER,progress REAL,has_violations INTEGER)""")

    def _task_owner(self, task_id: object) -> int:
        if type(task_id) is not int or task_id <= 0:
            raise AccessDenied()
        row = self.connection.execute("SELECT project_id FROM main.project_task WHERE id=?", (task_id,)).fetchone()
        if row is None:
            if task_id in self.deleted_task_owners:
                return self.deleted_task_owners[task_id]
            raise AccessDenied()
        return int(row[0])

    def _owners(self, table: str, row: Mapping[str, object]) -> set[int]:
        if not row:
            return set()
        if table == "task_dependencies":
            owners = {self._task_owner(row.get("task_id"))}
            if row.get("predecessor_task_id") is not None:
                owners.add(self._task_owner(row["predecessor_task_id"]))
            if row.get("predecessor_project_id") is not None:
                owners.add(int(row["predecessor_project_id"]))
            return owners
        if table == "task_tag":
            return {self._task_owner(row.get("task_id"))}
        owner = row.get("id") if table == "project" else row.get("project_id")
        if type(owner) is not int or owner <= 0:
            raise AccessDenied()
        if table == "resource_pool_assignment" and row.get("task_id") is not None:
            if self._task_owner(row["task_id"]) != owner:
                raise AccessDenied()
        return {owner}

    def _is_protected(self, table: str, old: dict[str, object], new: dict[str, object]) -> bool:
        if old == new:
            return False
        if table == "project":
            return old.get("project_type_id") != new.get("project_type_id")
        if table in _PROTECTED_DEFINITIONS:
            return True
        if table in {"project_property_value", "project_property_value_item"}:
            params = {row.get("param_id") for row in (old, new) if row}
            found = self.connection.execute("SELECT 1 FROM main.schema_parameters WHERE param_type='ENUM' "
                                            "AND param_id IN (SELECT value FROM json_each(?)) LIMIT 1", (json.dumps(list(params)),)).fetchone()
            return found is not None
        return False

    def _authorize(self, table: str, operation: str, before: str, after: str) -> int:
        try:
            old, new = json.loads(before), json.loads(after)
            if operation == "INSERT":
                old = self._existing_insert_target(table, new)
            if isinstance(self.access.actor, DeploymentActor):
                return 1
            if table in _SHARED_TABLES:
                self.access.require(self.store, Permission.SHARED)
                return 1
            if table == "project" and operation == "INSERT":
                self.access.require(self.store, Permission.CREATE)
                return 1
            owners = self._owners(table, old) | self._owners(table, new)
            permission = Permission.DELETE if table == "project" and operation == "DELETE" else Permission.EDIT
            if not self.access.global_permission(self.store, permission):
                self.access.require(self.store, permission, owners)
            if table == "project_task" and old.get("predecessor_id") != new.get("predecessor_id"):
                for row in (old, new):
                    if row.get("predecessor_id") is not None:
                        self.access.require(self.store, Permission.EDIT, {self._task_owner(row["predecessor_id"])})
            if self._is_protected(table, old, new):
                self.access.require(self.store, Permission.PROPERTIES)
            if table == "project_task" and operation == "DELETE":
                self.deleted_task_owners[int(old["id"])] = int(old["project_id"])
            return 1
        except AccessDenied as error:
            self.denial = error
            return 0

    def _existing_insert_target(self, table: str, row: dict[str, object]) -> dict[str, object]:
        """Authorize replaced owners and permit genuinely unchanged protected upserts."""
        keys = self.primary_keys[table]
        if not keys or any(row.get(key) is None for key in keys):
            return {}
        values = tuple(row[key] for key in keys)
        where = " AND ".join(f'"{key}"=?' for key in keys)
        cursor = self.connection.cursor()
        cursor.row_factory = sqlite3.Row
        found = cursor.execute(f"SELECT * FROM main.{table} WHERE {where}", values).fetchone()
        previous = dict(found) if found is not None else {}
        if previous and (table in _PROTECTED_DEFINITIONS or table in {"project", "project_property_value", "project_property_value_item"}):
            self.replaced_rows[(table, values)] = previous
        else:
            self.replaced_rows.pop((table, values), None)
        return previous

    def _audit(self, table: str, operation: str, before: str, after: str) -> int:
        old, new = json.loads(before), json.loads(after)
        if operation == "INSERT":
            key = (table, tuple(new.get(name) for name in self.primary_keys[table]))
            old = self.replaced_rows.pop(key, old)
        elif operation == "UPDATE":
            self.replaced_rows.pop((table, tuple(new.get(name) for name in self.primary_keys[table])), None)
        if table == "project" and operation == "INSERT":
            project_id = int(new["id"])
            if project_id in self.access.projects(self.store):
                self.connection.execute("INSERT OR IGNORE INTO temp.eppm_visible_project(id) VALUES(?)", (project_id,))
        if not self._is_protected(table, old, new):
            return 1
        row = new or old
        details = {"table": table, "operation": operation,
                   "fields": sorted(name for name in set(old) | set(new) if old.get(name) != new.get(name))}
        if row.get("param_id") is not None:
            details["property"] = str(row["param_id"])
        categorical_fields = {"project_type_id", "param_id", "param_type", "kind", "text_value", "value", "option_value"}
        details["changes"] = {
            name: {"before": old.get(name), "after": new.get(name)}
            for name in categorical_fields & (set(old) | set(new)) if old.get(name) != new.get(name)
        }
        target = row.get("project_id", row.get("id", "definition"))
        self.store.audit(self.access.policy.clock(), self.access.audit_actor, str(target),
                         "project.protected_property_change", self.access.actor.correlation_id, details)
        return 1
