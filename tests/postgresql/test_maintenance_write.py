"""Backups and operator callbacks retain atomicity, fresh sources and safe retries."""

from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from app.application.exceptions import DatabaseMaintenanceError
from app.infrastructure.postgresql.backup import PostgresBackup, restore_database
from app.infrastructure.postgresql.maintenance_write import backed_up_write
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.infrastructure.postgresql.pool_scenarios import apply_pool_scenarios, prepare_pool_scenarios
from app.infrastructure.postgresql.reset import flush_projects
from app.infrastructure.postgresql.seed_plan import source_fingerprint
from tests.postgresql.test_pool_seed_scenarios import install


def test_native_pre_reset_archive_restores_original_projects_and_exact_budgets(pg_database, restore_target, clients, tmp_path):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    fingerprint = operator.run(source_fingerprint)
    backup = PostgresBackup(pg_database.operator_url, tmp_path, tools=clients)
    assert backed_up_write(operator, backup, reason='reset', fingerprint=fingerprint,
                           operation=lambda c: flush_projects(c, flush_all=True))['projects_deleted'] == 5
    assert operator.run(lambda c: c.execute('SELECT count(*) FROM eppm.project').fetchone()) == (0,)
    archives = list(tmp_path.glob('*.dump'))
    assert len(archives) == 1
    restore_database(archives[0], restore_target.operator_url, tools=clients)
    with psycopg.connect(restore_target.operator_url) as connection:
        assert connection.execute('SELECT count(*),sum(planned_budget),sum(actual_budget) FROM eppm.project').fetchone() == (
            5, Decimal('1250000'), Decimal('842000'),
        )
        assert connection.execute('SELECT count(*) FROM eppm.project_task').fetchone() == (15,)
        assert connection.execute('SELECT count(*) FROM eppm.employee').fetchone() == (50,)


def test_scenario_database_retry_creates_one_real_pre_operation_archive(pg_database, restore_target, clients, tmp_path):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    plan = operator.run(lambda c: prepare_pool_scenarios(c, year=2026, seed=42))
    attempts = []

    def operation(connection):
        attempts.append(1)
        report = apply_pool_scenarios(connection, plan)
        if len(attempts) == 1:
            connection.execute("DO $$ BEGIN RAISE EXCEPTION 'retry' USING ERRCODE='40001'; END $$")
        return report

    result = backed_up_write(operator, PostgresBackup(pg_database.operator_url, tmp_path, tools=clients),
        reason='seed', fingerprint=plan.fingerprint, operation=operation)
    assert result['new_pools'] == 33 and result['applied']
    assert len(attempts) == 2
    archives = list(tmp_path.glob('*.dump'))
    assert len(archives) == 1
    restore_database(archives[0], restore_target.operator_url, tools=clients)
    with psycopg.connect(restore_target.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool').fetchone() == (0,)


def test_source_change_during_backup_prevents_reset_and_preserves_concurrent_edit(authorized, monkeypatch, tmp_path):
    operator = OperatorDatabase(authorized.setup.operator_url)
    fingerprint = operator.run(source_fingerprint)
    backup = PostgresBackup(authorized.setup.operator_url, tmp_path)

    def archive(reason):
        authorized.query("UPDATE eppm.project SET name='Concurrent edit' WHERE id=1", write=True)
        return tmp_path / 'archive.dump'

    monkeypatch.setattr(backup, 'create', archive)
    with pytest.raises(ValueError, match='changed during preparation'):
        backed_up_write(operator, backup, reason='reset', fingerprint=fingerprint, operation=flush_projects)
    assert authorized.query('SELECT name FROM eppm.project WHERE id=1') == [('Concurrent edit',)]


def test_failed_archive_prevents_any_database_mutation_and_hides_diagnostics(authorized, monkeypatch, tmp_path, caplog):
    operator = OperatorDatabase(authorized.setup.operator_url)
    backup = PostgresBackup(authorized.setup.operator_url, tmp_path)
    fingerprint = operator.run(source_fingerprint)

    def fail(reason):
        raise OSError('private diagnostic')

    monkeypatch.setattr(backup, 'create', fail)
    with pytest.raises(DatabaseMaintenanceError) as error:
        backed_up_write(operator, backup, reason='reset', fingerprint=fingerprint, operation=flush_projects)
    assert operator.run(source_fingerprint) == fingerprint
    assert 'private diagnostic' not in str(error.value) + caplog.text


def test_retry_rechecks_sources_and_preserves_an_edit_committed_after_the_first_attempt(authorized, tmp_path, monkeypatch):
    operator = OperatorDatabase(authorized.setup.operator_url)
    backup = PostgresBackup(authorized.setup.operator_url, tmp_path)
    fingerprint = operator.run(source_fingerprint)
    calls = []
    monkeypatch.setattr(backup, 'create', lambda reason: calls.append(reason) or Path('archive.dump'))

    def operation(connection):
        connection.execute("INSERT INTO eppm.resource_pool(name) VALUES ('Uncommitted pool')")
        authorized.query("UPDATE eppm.project SET name='Concurrent edit' WHERE id=1", write=True)
        connection.execute("DO $$ BEGIN RAISE EXCEPTION 'retry' USING ERRCODE='40001'; END $$")

    with pytest.raises(ValueError, match='changed during preparation'):
        backed_up_write(operator, backup, reason='seed', fingerprint=fingerprint, operation=operation)
    assert calls == ['seed']
    assert authorized.query('SELECT name FROM eppm.project WHERE id=1') == [('Concurrent edit',)]
    assert operator.run(lambda c: c.execute('SELECT count(*) FROM eppm.resource_pool').fetchone()) == (0,)


@pytest.mark.parametrize('code,expected_attempts', [('40001', 3), ('23505', 1), ('08006', 1)])
def test_exhausted_retry_constraint_and_uncertain_connection_errors_roll_back_without_repeating_archive(authorized, tmp_path, monkeypatch, code, expected_attempts):
    operator = OperatorDatabase(authorized.setup.operator_url)
    backup = PostgresBackup(authorized.setup.operator_url, tmp_path)
    fingerprint = operator.run(source_fingerprint)
    calls, attempts = [], []
    monkeypatch.setattr(backup, 'create', lambda reason: calls.append(reason) or Path('archive.dump'))

    def operation(connection):
        attempts.append(1)
        connection.execute("UPDATE eppm.project SET name='Rollback' WHERE id=1")
        connection.execute(f"DO $$ BEGIN RAISE EXCEPTION 'private diagnostic' USING ERRCODE='{code}'; END $$")

    with pytest.raises(DatabaseMaintenanceError, match='backup is retained'):
        backed_up_write(operator, backup, reason='seed', fingerprint=fingerprint, operation=operation)
    assert calls == ['seed']
    assert len(attempts) == expected_attempts
    assert operator.run(source_fingerprint) == fingerprint
