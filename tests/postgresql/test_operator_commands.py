"""Deployment wrappers use native maintenance and verified account operations."""

from functools import partial
import json

import psycopg
import pytest

from app.operator_services import create_maintenance_service
from app.infrastructure.postgresql.seed_plan import source_fingerprint
from tests.postgresql.test_access_service import identity, pg_access
from tests.postgresql.test_allocation_seed import allocations


@pytest.fixture
def operator_arguments(pg_database, clients, tmp_path, monkeypatch):
    monkeypatch.setenv('EPPM_TEST_OPERATOR_URL', pg_database.operator_url)
    monkeypatch.setattr('scripts.maintenance_cli.create_maintenance_service',
                        partial(create_maintenance_service, archive_tools=clients))
    return ['--url-variable', 'EPPM_TEST_OPERATOR_URL', '--backup-directory', str(tmp_path)]


def test_default_bulk_pool_scenario_and_reset_wrappers_keep_native_archive_policy(operator_arguments, pg_database, tmp_path, monkeypatch):
    from scripts import flush_database, seed_database, seed_defaults, seed_pool_scenarios

    service = create_maintenance_service(pg_database.operator_url)
    for command, options in (
        (seed_defaults, []), (seed_database, ['--projects', '2', '--min-tasks', '1', '--max-tasks', '1']),
        (seed_pool_scenarios, ['--year', '2026']), (seed_pool_scenarios, ['--year', '2026', '--apply']),
    ):
        monkeypatch.setattr('sys.argv', ['operator'] + operator_arguments + options)
        command.main()
    assert service.counts()['projects'] == 2
    assert len(list(tmp_path.glob('*.dump'))) == 2
    with psycopg.connect(pg_database.operator_url) as connection:
        pools = connection.execute('SELECT * FROM eppm.resource_pool ORDER BY id').fetchall()
    assert pools
    monkeypatch.setattr('sys.argv', ['operator'] + operator_arguments + ['--yes'])
    flush_database.main()
    assert service.counts()['projects'] == 0
    assert service.counts()['pools'] == len(pools)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT * FROM eppm.resource_pool ORDER BY id').fetchall() == pools
    assert len(list(tmp_path.glob('*.dump'))) == 3


def test_allocation_wrapper_previews_before_reviewed_apply_and_requires_explicit_clear(allocations, operator_arguments, monkeypatch, tmp_path, capsys):
    from scripts.pool_allocations import main

    before = allocations.database.run(source_fingerprint)
    prefix = ['operator'] + operator_arguments
    options = ['--overallocated-pools', '25', '--unstaffed-pools', '20']
    monkeypatch.setattr('sys.argv', prefix + ['generate'] + options)
    main()
    assert allocations.database.run(source_fingerprint) == before
    assert '"applied": false' in capsys.readouterr().out
    monkeypatch.setattr('sys.argv', prefix + ['generate', '--apply', '--expected-fingerprint', before] + options)
    main()
    assert len(list(tmp_path.glob('*.dump'))) == 1
    after = allocations.database.run(source_fingerprint)
    monkeypatch.setattr('sys.argv', prefix + ['clear'])
    main()
    assert allocations.database.run(source_fingerprint) == after
    monkeypatch.setattr('sys.argv', prefix + ['clear', '--apply'])
    main()
    assert len(list(tmp_path.glob('*.dump'))) == 2
    assert allocations.database.run(lambda c: c.execute('SELECT count(*) FROM eppm.resource_pool_assignment').fetchone()) == (0,)


def test_operator_factories_do_not_fall_back_to_runtime_credentials_or_sqlite(tmp_path, monkeypatch):
    from app.operator_services import create_deployment_access_service

    monkeypatch.delenv('DATABASE_OPERATOR_URL', raising=False)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://runtime@localhost/example')
    monkeypatch.setenv('DB_NAME', str(tmp_path / 'must-not-create.db'))
    for factory in (create_maintenance_service, create_deployment_access_service):
        with pytest.raises(ValueError, match='PostgreSQL database URL'):
            factory()
    assert list(tmp_path.iterdir()) == []


def test_access_command_bootstraps_only_verified_native_accounts_and_records_recovery(pg_access, monkeypatch, capsys):
    from scripts.access_admin import run

    cookie = pg_access.service.sign_in(identity('operator-verified-account'))
    actor = pg_access.service.actor(cookie)
    monkeypatch.setenv('EPPM_TEST_ACCESS_URL', pg_access.setup.operator_url)
    prefix = ['--url-variable', 'EPPM_TEST_ACCESS_URL']
    assert run(prefix + ['migrate']) == 0
    assert run(prefix + ['migrate']) == 0
    assert run(prefix + ['bootstrap-admin', '--user-id', '999']) == 1
    assert run(prefix + ['pending-accounts']) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row['id'] for row in rows] == [actor.user_id]
    assert run(prefix + ['bootstrap-admin', '--user-id', str(actor.user_id)]) == 0
    assert run(prefix + ['bootstrap-admin', '--user-id', str(actor.user_id)]) == 1
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.app_user SET status='disabled' WHERE id=%s", (actor.user_id,))
    assert run(prefix + ['recover-admin', '--user-id', str(actor.user_id), '--reason', '']) == 1
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        assert connection.execute('SELECT status FROM eppm.app_user WHERE id=%s', (actor.user_id,)).fetchone() == ('disabled',)
    assert run(prefix + ['recover-admin', '--user-id', str(actor.user_id), '--reason', 'Verified local recovery']) == 0
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.app_role_assignment WHERE user_id=%s AND role='access_admin'", (actor.user_id,)).fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM eppm.app_user WHERE status='active'").fetchone() == (1,)
        event = connection.execute("SELECT actor,details_json->>'reason' FROM eppm.app_security_audit WHERE action='access.recover'").fetchone()
        assert event[0].startswith('operator:') and event[1] == 'Verified local recovery'


def test_access_command_migrates_explicitly_and_reports_unmigrated_storage_safely(empty_database, monkeypatch, capsys):
    from scripts.access_admin import run
    from tests.postgresql.conftest import database_url
    from uuid import uuid4

    missing = 'eppm_missing_' + uuid4().hex
    monkeypatch.setenv('EPPM_TEST_ACCESS_URL', database_url(empty_database.operator_url, missing))
    prefix = ['--url-variable', 'EPPM_TEST_ACCESS_URL']
    assert run(prefix + ['pending-accounts']) == 1
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM pg_database WHERE datname=%s', (missing,)).fetchone() == (0,)
    monkeypatch.setenv('EPPM_TEST_ACCESS_URL', empty_database.operator_url)
    assert run(prefix + ['pending-accounts']) == 1
    assert run(prefix + ['migrate']) == 0
    assert run(prefix + ['pending-accounts']) == 0
    assert json.loads(capsys.readouterr().out) == []
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute('DROP TABLE eppm.app_user CASCADE')
    assert run(prefix + ['pending-accounts']) == 1
    assert empty_database.operator_url not in capsys.readouterr().err


def test_operator_recovery_permanently_closes_initial_setup_after_grant_removal(pg_access, monkeypatch):
    from scripts.access_admin import run

    actor = pg_access.service.actor(pg_access.service.sign_in(identity('recovered-first-admin')))
    monkeypatch.setenv('EPPM_TEST_ACCESS_URL', pg_access.setup.operator_url)
    prefix = ['--url-variable', 'EPPM_TEST_ACCESS_URL']
    assert run(prefix + ['recover-admin', '--user-id', str(actor.user_id), '--reason', 'Verified deployment appointment']) == 0
    with psycopg.connect(pg_access.setup.operator_url) as connection:
        connection.execute("DELETE FROM eppm.app_role_assignment WHERE role='access_admin'")
        assert connection.execute('SELECT bootstrap_complete FROM eppm.app_security_state').fetchone() == (True,)
    assert run(prefix + ['bootstrap-admin', '--user-id', str(actor.user_id)]) == 1


def test_pending_account_command_filters_before_limiting_and_pages_without_omissions(pg_database, monkeypatch, capsys):
    from scripts.access_admin import run

    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.app_user(id,status,display_name,created_at,updated_at)
            SELECT i,CASE WHEN i<=202 THEN 'active' ELSE 'pending' END,'Account ' || i,1000,1000
            FROM generate_series(1,205) i""")
        connection.execute("""INSERT INTO eppm.app_identity(user_id,issuer,subject)
            SELECT i,'https://issuer.example.test','subject-' || i FROM generate_series(1,205) i""")
    monkeypatch.setenv('EPPM_TEST_ACCESS_URL', pg_database.operator_url)
    prefix = ['--url-variable', 'EPPM_TEST_ACCESS_URL', 'pending-accounts']
    assert run(prefix + ['--limit', '2']) == 0
    assert [row['id'] for row in json.loads(capsys.readouterr().out)] == [203, 204]
    assert run(prefix + ['--after-id', '204', '--limit', '2']) == 0
    assert [row['id'] for row in json.loads(capsys.readouterr().out)] == [205]
    assert run(prefix + ['--after-id', '205']) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert run(prefix + ['--after-id', '-1']) == 1
    assert run(prefix + ['--limit', '201']) == 1


def test_explicit_application_cli_seeds_postgresql_and_reports_archive_failure_without_rendering_ui(pg_database, clients, tmp_path, monkeypatch):
    from app import main

    monkeypatch.setenv('DATABASE_OPERATOR_URL', pg_database.operator_url)
    monkeypatch.setenv('DATABASE_BACKUP_DIRECTORY', str(tmp_path))
    monkeypatch.setattr('app.operator_services.create_maintenance_service',
                        partial(create_maintenance_service, archive_tools=clients))
    monkeypatch.setattr('streamlit.runtime.exists', lambda: False)
    monkeypatch.setattr(main, 'run_app', lambda: pytest.fail('An explicit seed command must not render the UI.'))
    monkeypatch.setattr('sys.argv', ['operator', '--projects', '2'])
    main.main()
    assert create_maintenance_service().counts()['projects'] == 2
    assert len(list(tmp_path.glob('*.dump'))) == 1
    assert main.parse_cli_args(['--force-reseed', '--projects', '3', '--server.port', '9999']) == (True, 3)
    monkeypatch.setattr('sys.argv', ['operator'])
    assert not main._run_cli()
    failed_backup = tmp_path / 'not-a-directory'
    failed_backup.write_text('archive path conflict', encoding='utf-8')
    monkeypatch.setenv('DATABASE_BACKUP_DIRECTORY', str(failed_backup))
    monkeypatch.setattr('sys.argv', ['operator', '--projects', '2'])
    with pytest.raises(SystemExit) as error:
        main.main()
    assert error.value.code == 1
    assert create_maintenance_service().counts()['projects'] == 2


def test_named_environment_file_configures_native_operator_commands(pg_database, tmp_path, monkeypatch, capsys):
    from scripts.access_admin import run
    from scripts.maintenance_cli import add_operator_arguments, maintenance_service
    import argparse

    environment = tmp_path / 'operator.env'
    environment.write_text('EPPM_TEST_FILE_URL=' + pg_database.operator_url + '\n', encoding='utf-8')
    monkeypatch.delenv('EPPM_TEST_FILE_URL', raising=False)
    # dotenv writes into the environment, so register restoration with pytest.
    monkeypatch.setenv('EPPM_TEST_FILE_URL', '')
    prefix = ['--env-file', str(environment), '--url-variable', 'EPPM_TEST_FILE_URL']
    parser = argparse.ArgumentParser()
    add_operator_arguments(parser)
    assert maintenance_service(parser.parse_args(prefix)).counts()['projects'] == 0
    assert run(prefix + ['pending-accounts']) == 0
    assert json.loads(capsys.readouterr().out) == []
