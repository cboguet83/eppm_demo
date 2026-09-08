"""Regression coverage for SQLite handle ownership and cache revisions."""

from contextlib import closing
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from src.database.connection import get_db
from src.database.seeder import seed_default_data_if_empty
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.portfolio_repo import portfolio_revision


@pytest.mark.parametrize("operation", ["read", "write", "rollback"])
def test_task_repository_closes_connections_on_every_exit(
    tmp_path: Path, operation: str,
) -> None:
    """Keep the real connection alive to prove closure is not left to GC."""
    path = str(tmp_path / "tasks.db")
    seed_default_data_if_empty(path)
    repository = MilestoneRepository(path)
    tasks = repository.get_all_milestones()
    task_id, predecessor_id = (int(value) for value in tasks.id.iloc[:2])
    repository.save_task_dependencies(
        task_id, [{"predecessor_task_id": predecessor_id}],
    )
    connection = get_db(path)
    try:
        with patch("app.infrastructure.repositories.planning.get_db", return_value=connection):
            if operation == "read":
                assert not repository.get_all_milestones().empty
            elif operation == "write":
                assert repository.update_dates(task_id, "2026-01-01", "2026-01-02")
            else:
                with pytest.raises(sqlite3.IntegrityError):
                    repository.save_task_dependencies(
                        task_id, [{"predecessor_task_id": -1}],
                    )
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    finally:
        connection.close()

    if operation == "rollback":
        dependencies = repository.get_task_dependencies(task_id)
        assert [row["predecessor_task_id"] for row in dependencies] == [predecessor_id]
    elif operation == "write":
        updated = repository.get_all_milestones().set_index("id").loc[task_id]
        assert updated.start_date == "2026-01-01"
        assert updated.end_date == "2026-01-02"


@pytest.mark.parametrize("journal_mode", ["DELETE", "WAL"])
def test_revision_tracks_commits_with_unchanged_file_metadata(
    tmp_path: Path, journal_mode: str,
) -> None:
    """Detect equal-size edits and reused WAL frames without timestamp changes."""
    path = tmp_path / "revision.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"PRAGMA journal_mode={journal_mode}")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('first')")
        connection.commit()
        metadata = path.stat()
        with patch.object(Path, "stat", return_value=metadata):
            before = portfolio_revision(str(path))
            assert portfolio_revision(str(path)) == before
            connection.execute("UPDATE sample SET value='other'")
            connection.commit()
            after = portfolio_revision(str(path))
            assert after != before
            assert portfolio_revision(str(path)) == after
            if journal_mode == "WAL":
                connection.execute("PRAGMA wal_checkpoint(RESTART)")
                connection.execute("UPDATE sample SET value='third'")
                connection.commit()
                assert portfolio_revision(str(path)) != after
