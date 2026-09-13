"""Real database startup, backup, reset, and safe maintenance boundaries."""

from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.application.exceptions import DatabaseMaintenanceError
from app.application.ports.maintenance import SeedRequest
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.schema_init import init_db
from app.infrastructure.database.seeder import seed_default_data_if_empty
from app.operator_services import create_maintenance_service


@pytest.fixture
def database(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    return str(directory / "maintenance.db")


def test_ordinary_startup_is_idempotent_and_preserves_existing_catalog(database):
    service = create_maintenance_service(database)
    service.startup(projects=20)
    counts = service.counts()
    assert counts["projects"] == counts["project_types"] == 5
    assert counts["tasks"] == 15
    assert counts["dependencies"] > 0 and counts["property_values"] > 0
    assert counts["pools"] == 103
    with closing(get_db(database)) as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migration ORDER BY version"
        ).fetchall()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    before_backups = list(Path(database).parent.glob("backups/*.db"))
    service.startup()
    assert service.counts() == counts
    assert list(Path(database).parent.glob("backups/*.db")) == before_backups
    with closing(get_db(database)) as connection:
        assert (
            connection.execute("SELECT version FROM schema_migration ORDER BY version").fetchall()
            == versions
        )


def test_forced_startup_retains_one_recoverable_backup_per_operation(database):
    service = create_maintenance_service(database)
    service.startup()
    backups_before = set(Path(database).parent.glob("backups/*.db"))
    service.startup(force=True, projects=2)
    assert service.counts()["projects"] == 2
    new_backups = set(Path(database).parent.glob("backups/*.db")) - backups_before
    assert len(new_backups) == 1
    with closing(sqlite3.connect(new_backups.pop())) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 5
    service.startup(force=True, projects=0)
    assert service.counts()["projects"] == 5
    assert len(set(Path(database).parent.glob("backups/*.db")) - backups_before) == 2


@pytest.mark.parametrize(
    "seed_request",
    [
        SeedRequest(projects=-1),
        SeedRequest(min_tasks=-1),
        SeedRequest(min_tasks=3, max_tasks=2),
        SeedRequest(max_tasks=51),
        SeedRequest(projects="bad"),
    ],
)
def test_invalid_seed_requests_do_not_create_database_or_backup(database, seed_request):
    with pytest.raises(ValueError, match="project or task count"):
        create_maintenance_service(database).seed_projects(seed_request)
    assert not Path(database).exists()
    assert not (Path(database).parent / "backups").exists()


@pytest.mark.parametrize("count", [-1, "bad"])
def test_invalid_startup_counts_fail_before_initialization(database, count):
    with pytest.raises(ValueError, match="project count"):
        create_maintenance_service(database).startup(projects=count)
    assert not Path(database).exists()


def test_explicit_resets_keep_constraints_and_return_real_counts(database):
    service = create_maintenance_service(database)
    service.startup()
    result = service.flush()
    assert result["projects_deleted"] == 5 and result["tasks_deleted"] == 15
    assert service.counts()["projects"] == 0
    assert service.counts()["project_types"] == 5
    service.flush(flush_all=True)
    counts = service.counts()
    assert counts["project_types"] == 1 and counts["pools"] == 0
    with closing(get_db(database)) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM schema_parameters").fetchone()[0] == 0


def test_backup_failure_aborts_layered_seed_before_existing_data_changes(database, monkeypatch):
    import app.infrastructure.database.backup as backups

    service = create_maintenance_service(database)
    service.startup()
    before = service.counts()

    def fail_backup(*args, **kwargs):
        raise OSError("private filesystem detail")

    monkeypatch.setattr(backups, "backup_database", fail_backup)
    with pytest.raises(DatabaseMaintenanceError) as failure:
        service.seed_projects(SeedRequest(projects=2))
    assert isinstance(failure.value.__cause__, OSError)
    assert "private filesystem detail" not in str(failure.value)
    assert service.counts() == before


def test_failed_reset_rolls_back_prior_child_record_deletions(database):
    service = create_maintenance_service(database)
    service.startup()
    before = service.counts()
    with closing(get_db(database)) as connection, connection:
        connection.execute("""CREATE TRIGGER prevent_project_reset BEFORE DELETE ON project
            BEGIN SELECT RAISE(ABORT, 'reset refused'); END""")
    with pytest.raises(DatabaseMaintenanceError) as failure:
        service.flush()
    assert isinstance(failure.value.__cause__, sqlite3.IntegrityError)
    assert service.counts() == before
    with closing(get_db(database)) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_unavailable_storage_has_safe_maintenance_errors(tmp_path, caplog):
    path = str(tmp_path / "private-dir" / "missing.db")
    with pytest.raises(DatabaseMaintenanceError) as failure:
        create_maintenance_service(path).counts()
    assert isinstance(failure.value.__cause__, sqlite3.DatabaseError)
    assert path not in str(failure.value) + caplog.text


def test_default_seed_does_not_misclassify_schema_errors_as_empty_database(database):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE schema_migration(unexpected TEXT)")
    with pytest.raises(sqlite3.OperationalError, match="no such column"):
        seed_default_data_if_empty(database)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == [("schema_migration",)]


def test_initialize_then_seed_handles_an_empty_database_file(database):
    Path(database).touch()
    seed_default_data_if_empty(database)
    assert create_maintenance_service(database).counts()["projects"] == 5
    init_db(database)
    assert create_maintenance_service(database).counts()["projects"] == 5


def test_pool_scenario_service_preserves_preview_and_idempotence(database, monkeypatch):
    import app.infrastructure.database.pool_scenarios as pools

    service = create_maintenance_service(database)
    with monkeypatch.context() as patch:
        patch.setattr(
            pools, "seed_pool_scenarios", lambda *args, **kwargs: {"new_pools": 0, "new_groups": 0}
        )
        service.startup()
    before = service.counts()
    preview = service.seed_pool_scenarios(year=2026)
    assert preview["new_pools"] == 100 and preview["applied"] is False
    assert service.counts() == before
    applied = service.seed_pool_scenarios(year=2026, apply=True)
    assert applied["applied"] is True
    assert service.counts()["pools"] == 103
    assert service.seed_pool_scenarios(apply=True)["already_seeded"] is True


@pytest.mark.parametrize("options", [{"year": 0}, {"year": "bad"}, {"seed": None}])
def test_pool_scenario_service_rejects_malformed_options_before_storage(database, options):
    with pytest.raises(ValueError, match="scenario"):
        create_maintenance_service(database).seed_pool_scenarios(**options)
    assert not Path(database).exists()


def run_cli(*arguments):
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_seed_and_flush_commands_use_the_migrated_service(database):
    seeded = run_cli(
        "scripts/seed_database.py", "--db-path", database, "--projects", "2", "--max-tasks", "0"
    )
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr
    assert create_maintenance_service(database).counts()["projects"] == 2
    flushed = run_cli("-m", "scripts.flush_database", "--db-path", database, "--yes")
    assert flushed.returncode == 0, flushed.stdout + flushed.stderr
    assert create_maintenance_service(database).counts()["projects"] == 0
    failed = run_cli("-m", "scripts.seed_database", "--db-path", database, "--projects", "-1")
    assert failed.returncode == 1
    assert "Invalid project or task count" in failed.stdout + failed.stderr
    assert "Traceback" not in failed.stdout + failed.stderr


def test_default_and_pool_commands_keep_existing_entrypoint_behavior(database):
    import json

    seeded = run_cli("-m", "scripts.seed_defaults", "--db-path", database)
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr
    assert create_maintenance_service(database).counts()["projects"] == 5
    preview = run_cli("scripts/seed_pool_scenarios.py", "--db", database)
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert json.loads(preview.stdout)["already_seeded"] is True
