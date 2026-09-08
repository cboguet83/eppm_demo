"""Project types, applicability, and effective template rules."""

from typing import Any

import pandas as pd

from src.database.connection import get_db
from src.database.property_store import effective_template, write_value


class ProjectTypeRepository:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path

    def get_all_types(self) -> pd.DataFrame:
        with get_db(self.db_path) as conn:
            return pd.read_sql("SELECT * FROM project_type ORDER BY is_general DESC, name", conn)

    def create_type(self, name: str, description: str = "") -> int:
        if not name.strip():
            raise ValueError("Project type name is required")
        with get_db(self.db_path) as conn:
            return int(conn.execute("INSERT INTO project_type(name, description) VALUES (?, ?)", (name.strip(), description.strip())).lastrowid)

    def update_type(self, type_id: int, name: str, description: str = "") -> None:
        if not name.strip():
            raise ValueError("Project type name is required")
        with get_db(self.db_path) as conn:
            general = conn.execute("SELECT is_general FROM project_type WHERE id=?", (type_id,)).fetchone()
            if not general:
                raise ValueError("Unknown project type")
            if general[0] and name != "General":
                raise ValueError("The General type cannot be renamed")
            conn.execute("UPDATE project_type SET name=?, description=? WHERE id=?", (name.strip(), description.strip(), type_id))

    def delete_type(self, type_id: int) -> None:
        with get_db(self.db_path) as conn:
            row = conn.execute("SELECT is_general FROM project_type WHERE id=?", (type_id,)).fetchone()
            if row and row[0]:
                raise ValueError("The General type cannot be deleted")
            if conn.execute("SELECT 1 FROM project WHERE project_type_id=?", (type_id,)).fetchone():
                raise ValueError("Reassign this type's projects before deleting it")
            # A selected-only property must retain at least one applicable type.
            if conn.execute("""SELECT 1 FROM project_type_property m JOIN schema_parameters p USING(param_id)
                WHERE m.project_type_id=? AND p.applies_to_all=0 AND NOT EXISTS
                (SELECT 1 FROM project_type_property other WHERE other.param_id=m.param_id AND other.project_type_id<>?)""", (type_id, type_id)).fetchone():
                raise ValueError("Assign this type's exclusive properties to another type first")
            conn.execute("DELETE FROM project_type WHERE id=?", (type_id,))

    def get_template(self, type_id: int) -> pd.DataFrame:
        with get_db(self.db_path) as conn:
            return pd.DataFrame(effective_template(conn, type_id))

    def get_applicability(self, param_id: str) -> tuple[bool, list[int]]:
        with get_db(self.db_path) as conn:
            row = conn.execute("SELECT applies_to_all FROM schema_parameters WHERE param_id=?", (param_id,)).fetchone()
            if not row:
                raise ValueError("Unknown property")
            return bool(row[0]), [r[0] for r in conn.execute("SELECT project_type_id FROM project_type_property WHERE param_id=? ORDER BY project_type_id", (param_id,))]

    @staticmethod
    def set_applicability_on_connection(conn, param_id: str, applies_to_all: bool, type_ids: list[int]) -> None:
        if not applies_to_all and not type_ids:
            raise ValueError("Select at least one project type")
        updated = conn.execute("UPDATE schema_parameters SET applies_to_all=? WHERE param_id=?", (int(applies_to_all), param_id))
        if not updated.rowcount:
            raise ValueError("Unknown property")
        conn.execute("DELETE FROM project_type_property WHERE param_id=?", (param_id,))
        if not applies_to_all:
            conn.executemany("INSERT INTO project_type_property(project_type_id,param_id) VALUES (?,?)", [(tid, param_id) for tid in sorted(set(type_ids))])

    def set_applicability(self, param_id: str, applies_to_all: bool, type_ids: list[int] | None = None) -> None:
        with get_db(self.db_path) as conn:
            self.set_applicability_on_connection(conn, param_id, applies_to_all, type_ids or [])

    def save_rule(self, type_id: int, param_id: str, mandatory_override: bool | None = None, *, has_default: bool = False, default_value: Any = None) -> None:
        with get_db(self.db_path) as conn:
            if param_id not in {p["param_id"] for p in effective_template(conn, type_id)}:
                raise ValueError("Property does not apply to this type")
            conn.execute("""INSERT INTO project_type_property_rule(project_type_id,param_id,mandatory_override) VALUES (?,?,?)
                ON CONFLICT(project_type_id,param_id) DO UPDATE SET mandatory_override=excluded.mandatory_override""", (type_id, param_id, mandatory_override))
            if has_default:
                write_value(conn, type_id, param_id, default_value, defaults=True)
            else:
                conn.execute("DELETE FROM project_type_property_default WHERE project_type_id=? AND param_id=?", (type_id, param_id))
