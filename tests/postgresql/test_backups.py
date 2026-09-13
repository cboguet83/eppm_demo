"""Real PostgreSQL archives preserve business truth, grants and private actor binding."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import subprocess
from types import SimpleNamespace

import psycopg
import pytest

from app.application.exceptions import DatabaseMaintenanceError
from app.application.services.finance import FinanceService
from app.infrastructure.postgresql.authorization import ActorBinding
from app.infrastructure.postgresql.backup import PostgresBackup, PostgresTools, restore_database
from app.infrastructure.postgresql.dashboard import PostgresDashboardReader
from app.infrastructure.postgresql.finance import PostgresFinanceGateway
from app.infrastructure.postgresql.pool import Database
from app.shared.config.database import DatabaseConfig


def test_archive_restore_preserves_exact_finance_actor_scope_and_revision_incarnation(authorized, restore_target, tmp_path, clients):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project SET planned_budget=%s WHERE id=1', (Decimal('9007199254740993.01'),))
        connection.execute("INSERT INTO eppm.wbs(code) VALUES ('ARCHIVE')")
    access = authorized.binding(4).access
    finance = FinanceService(PostgresFinanceGateway(authorized.database, authorized.key, access=access))
    plan = finance.save([{'code': 'ARCHIVE', 'amounts': {'2026': '9007199254740993.01'}}],
                        base_id=None, name='Approved archive', status='Approved', year=2026)
    source_revision = PostgresDashboardReader(authorized.database, authorized.key, access=authorized.binding().access).revision()
    archive = PostgresBackup(authorized.setup.operator_url, tmp_path, tools=clients).create('recovery-check')
    assert archive.read_bytes().startswith(b'PGDMP') and not list(tmp_path.glob('*.incomplete'))
    restore_database(archive, restore_target.operator_url, tools=clients)
    restored = Database(DatabaseConfig(restore_target.runtime_url, pool_min=1, pool_max=2))
    restored.open()
    try:
        rows = restored.run(lambda connection: connection.execute('SELECT id,planned_budget FROM eppm.project ORDER BY id').fetchall(),
                            bind=ActorBinding(authorized.binding().access, authorized.key))
        assert rows[0] == (1, Decimal('9007199254740993.01')) and [row[0] for row in rows] == [1, 2]
        restored_finance = FinanceService(PostgresFinanceGateway(restored, authorized.key, access=access))
        assert restored_finance.view(plan).selected.rows[0].amounts == {2026: Decimal('9007199254740993.01')}
        with pytest.raises(psycopg.errors.CheckViolation, match='immutable'):
            restored.run(lambda connection: connection.execute('UPDATE eppm.finance_snapshot SET name=%s WHERE id=%s',
                         ('Tamper', plan)), write=True, bind=ActorBinding(access, authorized.key))
        new_revision = PostgresDashboardReader(restored, authorized.key, access=authorized.binding().access).revision()
        assert new_revision != source_revision
    finally:
        restored.close()
    with psycopg.connect(restore_target.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.app_role_assignment').fetchone()[0] > 0
        assert connection.execute('SELECT count(*) FROM eppm.project').fetchone() == (3,)


def test_restore_refuses_a_populated_target_and_preserves_its_rows(authorized, tmp_path, clients):
    archive = PostgresBackup(authorized.setup.operator_url, tmp_path, tools=clients).create()
    with pytest.raises(ValueError, match='separate empty'):
        restore_database(archive, authorized.setup.operator_url, tools=clients)
    assert authorized.query('SELECT id,name FROM eppm.project ORDER BY id') == [(1, 'Editable'), (2, 'Read only')]


def test_corrupt_archive_restore_rolls_back_all_schema_and_data(authorized, restore_target, tmp_path, clients):
    archive = PostgresBackup(authorized.setup.operator_url, tmp_path, tools=clients).create()
    truncated = tmp_path / 'truncated.dump'
    content = archive.read_bytes()
    truncated.write_bytes(content[:len(content) // 2])
    with pytest.raises(DatabaseMaintenanceError):
        restore_database(truncated, restore_target.operator_url, tools=clients)
    with psycopg.connect(restore_target.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM pg_namespace WHERE nspname='eppm'").fetchone() == (0,)
    assert archive.exists()


def test_failed_dump_never_publishes_an_archive_or_exposes_client_diagnostics(tmp_path, monkeypatch, caplog):
    def fail(command, **options):
        assert 'private-password' not in repr(command)
        assert options['env']['PGPASSWORD'] == 'private-password'
        options['stdout'].write(b'incomplete archive')
        return SimpleNamespace(returncode=1, stderr=b'private-password and internal server details')
    monkeypatch.setattr('app.infrastructure.postgresql.backup.subprocess.run', fail)
    backup = PostgresBackup('postgresql://app:private-password@localhost/example', tmp_path)
    with pytest.raises(DatabaseMaintenanceError) as failure:
        backup.create()
    assert list(tmp_path.glob('*.incomplete')) and not list(tmp_path.glob('*.dump'))
    assert 'private-password' not in str(failure.value) + caplog.text


@pytest.mark.parametrize('error', [OSError('private internal details'), subprocess.TimeoutExpired('private-command', 1)])
def test_client_failure_and_timeout_are_safe_and_never_retried(error, monkeypatch, caplog):
    calls = []
    def fail(*args, **kwargs):
        calls.append(True)
        raise error
    monkeypatch.setattr('app.infrastructure.postgresql.backup.subprocess.run', fail)
    with pytest.raises(DatabaseMaintenanceError) as failure:
        PostgresTools().run('pg_dump', (), url='postgresql://app:private-password@localhost/example')
    assert calls == [True] and 'private-' not in str(failure.value) + caplog.text


def test_client_environment_uses_only_explicit_libpq_values(monkeypatch):
    monkeypatch.setenv('PGPASSWORD', 'inherited-operator-password')
    monkeypatch.setenv('PGSERVICE', 'inherited-service')
    environment = PostgresTools()._environment('postgresql://app:explicit-password@localhost/example?sslmode=require')
    assert environment['PGPASSWORD'] == 'explicit-password' and environment['PGSSLMODE'] == 'require'
    assert 'PGSERVICE' not in environment
    assert 'PGPASSWORD' not in PostgresTools()._environment(None)
    with pytest.raises(ValueError):
        PostgresTools().run('sh', ())
    with pytest.raises(ValueError):
        PostgresTools(timeout=float('inf'))


def test_archive_names_are_exclusive_and_reason_is_not_a_path(tmp_path, monkeypatch):
    def succeed(command, **options):
        if options['stdout'] != subprocess.DEVNULL:
            options['stdout'].write(b'PGDMP synthetic external boundary')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('app.infrastructure.postgresql.backup.subprocess.run', succeed)
    backup = PostgresBackup('postgresql://app:example@localhost/example', tmp_path,
                            clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    first, second = backup.create(), backup.create()
    assert first != second and first.read_bytes() == second.read_bytes()
    with pytest.raises(ValueError):
        backup.create('../outside')
    with pytest.raises(ValueError):
        restore_database(first, 'postgresql://app:example@localhost/postgres')


def test_backup_filesystem_failure_preserves_safe_operator_error(tmp_path):
    directory = tmp_path / 'not-a-directory'
    directory.write_text('Existing operator file', encoding='utf-8')
    with pytest.raises(DatabaseMaintenanceError):
        PostgresBackup('postgresql://app:example@localhost/example', directory).create()
    assert directory.read_text(encoding='utf-8') == 'Existing operator file'


def test_missing_restore_file_and_unsupported_connection_option_fail_safely(tmp_path, caplog):
    with pytest.raises(DatabaseMaintenanceError):
        restore_database(tmp_path / 'missing.dump', 'postgresql://app:private-password@localhost/example')
    with pytest.raises(DatabaseMaintenanceError):
        PostgresTools().run('pg_dump', (), url='postgresql://app:private-password@localhost/example?replication=database')
    assert 'private-password' not in caplog.text


def test_operator_cli_backs_up_and_restores_only_the_explicit_target(authorized, restore_target, tmp_path, clients, monkeypatch):
    from scripts import postgresql_admin

    monkeypatch.setattr(postgresql_admin, 'setup_logging', lambda: None)
    monkeypatch.setenv('TEST_ARCHIVE_OPERATOR_URL', authorized.setup.operator_url)
    monkeypatch.setattr('sys.argv', ['postgresql_admin', '--url-variable', 'TEST_ARCHIVE_OPERATOR_URL',
                                    '--backup-directory', str(tmp_path), 'backup'])
    postgresql_admin.main(archive_tools=clients)
    archive, = tmp_path.glob('*.dump')
    monkeypatch.setenv('TEST_ARCHIVE_OPERATOR_URL', restore_target.operator_url)
    monkeypatch.setattr('sys.argv', ['postgresql_admin', '--url-variable', 'TEST_ARCHIVE_OPERATOR_URL',
                                    '--archive', str(archive), 'restore'])
    postgresql_admin.main(archive_tools=clients)
    with psycopg.connect(restore_target.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.project').fetchone() == (3,)
    with pytest.raises(SystemExit) as failure:
        postgresql_admin.main(archive_tools=clients)
    assert failure.value.code == 1
