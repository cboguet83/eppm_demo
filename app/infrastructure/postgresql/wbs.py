"""Native WBS catalog and global-capacity queries within project transactions."""

import psycopg

from app.domain.projects.wbs import WbsAllocation, WbsOption, validate_availability


class PostgresWbsStore:
    """Keep WBS edits and project changes in the same authorized transaction."""

    def __init__(self, connection: psycopg.Connection) -> None:
        """Retain the caller's connection without taking ownership of its lifetime."""
        self.connection = connection

    def wbs_options(self, project_id: int | None) -> list[WbsOption]:
        """Read global remainder without exposing hidden project identities."""
        choices: dict[int, WbsOption] = {}
        for identity, code, description, percentage, status in self.connection.execute(
            'SELECT id,code,description,percentage,status FROM eppm.wbs_allocation_facts(%s)', (project_id,)
        ):
            option = choices.setdefault(identity, WbsOption(id=identity, code=code, description=description, available=100))
            if percentage is not None and status != 'Cancelled':
                option['available'] -= int(percentage)
        return list(choices.values())

    def wbs_allocations(self, project_id: int) -> list[WbsAllocation]:
        """Return only visible project allocations in stable WBS order."""
        return [WbsAllocation(wbs_id=row[0], percentage=row[1]) for row in self.connection.execute(
            'SELECT wbs_id,percentage::integer FROM eppm.project_wbs WHERE project_id=%s ORDER BY wbs_id', (project_id,))]

    def replace_wbs(self, project_id: int, allocations: list[WbsAllocation]) -> None:
        """Validate changed shares while avoiding unrelated reads for a no-op.

        Args:
            project_id: Project whose master mutation already checked edit access.
            allocations: Normalized requested whole-percentage shares.
        """
        if sorted(allocations, key=lambda row: row['wbs_id']) == self.wbs_allocations(project_id):
            return
        if not allocations:
            # Empty replacement cannot consume global capacity. Keep the owner-
            # authorized delete without reading unrelated project status rows.
            self.connection.execute('DELETE FROM eppm.project_wbs WHERE project_id=%s', (project_id,))
            return
        options = self.wbs_options(project_id)
        status = self.connection.execute('SELECT status FROM eppm.project WHERE id=%s', (project_id,)).fetchone()[0]
        if status == 'Cancelled':
            options = [WbsOption(**{**option, 'available': 100}) for option in options]
        validate_availability(allocations, options)
        self.connection.execute('DELETE FROM eppm.project_wbs WHERE project_id=%s', (project_id,))
        with self.connection.cursor() as cursor:
            cursor.executemany('INSERT INTO eppm.project_wbs(project_id,wbs_id,percentage) VALUES (%s,%s,%s)',
                               [(project_id, row['wbs_id'], row['percentage']) for row in allocations])

    def save_wbs(self, code: str, description: str, wbs_id: int | None) -> int:
        """Preserve reference identity and the existing duplicate-code message."""
        duplicate = self.connection.execute('SELECT id FROM eppm.wbs WHERE code=%s', (code,)).fetchone()
        if duplicate is not None and duplicate[0] != wbs_id:
            raise ValueError('A WBS with this code already exists.')
        if wbs_id is None:
            return self.connection.execute('INSERT INTO eppm.wbs(code,description) VALUES (%s,%s) RETURNING id', (code, description)).fetchone()[0]
        if not self.connection.execute('UPDATE eppm.wbs SET code=%s,description=%s WHERE id=%s', (code, description, wbs_id)).rowcount:
            raise ValueError('The selected WBS no longer exists.')
        return wbs_id

    def delete_wbs(self, wbs_id: int) -> None:
        """Keep referenced entries protected, including zero-percentage assignments."""
        if self.connection.execute('SELECT 1 FROM eppm.project_wbs WHERE wbs_id=%s LIMIT 1', (wbs_id,)).fetchone():
            raise ValueError('This WBS is assigned to a project. Remove its project assignments before deleting it.')
        if not self.connection.execute('DELETE FROM eppm.wbs WHERE id=%s', (wbs_id,)).rowcount:
            raise ValueError('The selected WBS no longer exists.')
