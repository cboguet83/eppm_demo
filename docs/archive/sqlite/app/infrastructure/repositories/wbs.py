"""WBS SQL operations on the caller's authorized SQLite transaction."""

import sqlite3

from app.domain.projects.wbs import WbsAllocation, WbsOption, validate_availability


class SqliteWbsStore:
    """Share the project transaction for catalog lookups and atomic allocation saves."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Retain the connection without owning its lifetime."""
        self._connection = connection

    def wbs_options(self, project_id: int | None) -> list[WbsOption]:
        """Expose only global availability, never hidden project identities.

        Global usage deliberately reads main.project_wbs: the cap includes projects
        outside the caller's scope. The edited project's saved share is reusable.
        """
        return [WbsOption(id=row[0], code=row[1], description=row[2], available=row[3])
                for row in self._connection.execute("""SELECT w.id,w.code,w.description,
                    100-COALESCE(used.percentage,0) FROM wbs w LEFT JOIN (
                        SELECT wbs_id,SUM(percentage) AS percentage FROM main.project_wbs
                        WHERE (? IS NULL OR project_id!=?) GROUP BY wbs_id
                    ) used ON used.wbs_id=w.id ORDER BY w.code""", (project_id, project_id))]

    def wbs_allocations(self, project_id: int) -> list[WbsAllocation]:
        """Read only assignments visible through the project-scoped view."""
        return [WbsAllocation(wbs_id=row[0], percentage=row[1]) for row in self._connection.execute(
            "SELECT wbs_id,percentage FROM project_wbs WHERE project_id=? ORDER BY wbs_id", (project_id,))]

    def replace_wbs(self, project_id: int, allocations: list[WbsAllocation]) -> None:
        """Validate the locked global total before replacing a project's allocations."""
        validate_availability(allocations, self.wbs_options(project_id))
        self._connection.execute("DELETE FROM main.project_wbs WHERE project_id=?", (project_id,))
        self._connection.executemany("INSERT INTO main.project_wbs(project_id,wbs_id,percentage) VALUES(?,?,?)",
                                     [(project_id, row["wbs_id"], row["percentage"]) for row in allocations])

    def save_wbs(self, code: str, description: str, wbs_id: int | None) -> int:
        """Preserve reference identity when editing its code or description."""
        duplicate = self._connection.execute("SELECT id FROM wbs WHERE code=?", (code,)).fetchone()
        if duplicate is not None and duplicate[0] != wbs_id:
            raise ValueError("A WBS with this code already exists.")
        if wbs_id is None:
            cursor = self._connection.execute("INSERT INTO main.wbs(code,description) VALUES(?,?)", (code, description))
            assert cursor.lastrowid is not None
            return cursor.lastrowid
        if not self._connection.execute("UPDATE main.wbs SET code=?,description=? WHERE id=?", (code, description, wbs_id)).rowcount:
            raise ValueError("The selected WBS no longer exists.")
        return wbs_id

    def delete_wbs(self, wbs_id: int) -> None:
        """Explain protected references instead of silently deleting allocations."""
        if self._connection.execute("SELECT 1 FROM main.project_wbs WHERE wbs_id=? LIMIT 1", (wbs_id,)).fetchone():
            raise ValueError("This WBS is assigned to a project. Remove its project assignments before deleting it.")
        if not self._connection.execute("DELETE FROM main.wbs WHERE id=?", (wbs_id,)).rowcount:
            raise ValueError("The selected WBS no longer exists.")
