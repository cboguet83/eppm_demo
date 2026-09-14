"""Complete explicit maintenance port with no runtime initialization side effects."""

from dataclasses import replace
import socket

import psycopg
import pytest

from app.application.exceptions import DatabaseMaintenanceError
from app.application.ports.maintenance import SeedRequest
from app.application.services.maintenance import MaintenanceService
from app.domain.resources.allocation_generation import AllocationGenerationRequest
from app.infrastructure.postgresql.maintenance_gateway import PostgresMaintenanceGateway


def test_explicit_operator_startup_migrates_once_and_forced_generation_keeps_one_archive_per_mutation(empty_database, clients, tmp_path):
    gateway = PostgresMaintenanceGateway(empty_database.operator_url, tmp_path, archive_tools=clients, default_seed_year=2026)
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute("SELECT to_regnamespace('eppm')").fetchone() == (None,)
    service = MaintenanceService(gateway)
    service.startup(projects=20)
    before = service.counts()
    assert before['projects'] == 5 and before['pools'] == 33
    assert len(list(tmp_path.glob('*.dump'))) == 1
    service.startup()
    assert service.counts() == before
    assert len(list(tmp_path.glob('*.dump'))) == 1
    service.startup(force=True, projects=2)
    assert service.counts()['projects'] == 2
    assert len(list(tmp_path.glob('*.dump'))) == 2
    service.startup(force=True, projects=0)
    assert service.counts() == before
    assert len(list(tmp_path.glob('*.dump'))) == 3


@pytest.mark.parametrize('operation,options', [
    ('startup', {'projects': -1}), ('startup', {'projects': 'bad'}),
    ('projects', {'projects': -1}), ('projects', {'projects': 'bad'}),
    ('projects', {'min_tasks': -1}), ('projects', {'min_tasks': 3, 'max_tasks': 2}),
    ('projects', {'max_tasks': 51}),
    ('allocations', {'allocated_pools_pct': -1}),
    ('scenarios', {'year': 0}), ('scenarios', {'year': 'bad'}), ('scenarios', {'seed': None}),
])
def test_invalid_requests_fail_before_operator_connection_or_archive(tmp_path, monkeypatch, operation, options):
    def unexpected_connection(*args, **kwargs):
        pytest.fail('Invalid options must fail before opening a database connection.')
    monkeypatch.setattr(psycopg, 'connect', unexpected_connection)
    service = MaintenanceService(PostgresMaintenanceGateway('postgresql://operator@localhost/example', tmp_path))
    with pytest.raises(ValueError):
        if operation == 'startup':
            service.startup(**options)
        elif operation == 'projects':
            service.seed_projects(SeedRequest(**options))
        elif operation == 'allocations':
            service.generate_pool_allocations(replace(AllocationGenerationRequest(), **options), apply=True)
        else:
            service.seed_pool_scenarios(**options, apply=True)
    assert list(tmp_path.iterdir()) == []


def test_failed_reset_rolls_back_deleted_children_and_retains_its_archive(pg_database, clients, tmp_path):
    from app.infrastructure.postgresql.seed_plan import source_fingerprint

    gateway = PostgresMaintenanceGateway(pg_database.operator_url, tmp_path, archive_tools=clients)
    service = MaintenanceService(gateway)
    service.startup()
    before = service.counts(), gateway.database.run(source_fingerprint)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.refuse_test_reset() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private reset refusal'
            USING ERRCODE='23514'; END $$""")
        connection.execute("CREATE TRIGGER refuse_test_reset BEFORE DELETE ON eppm.project "
                           "FOR EACH ROW EXECUTE FUNCTION eppm.refuse_test_reset()")
    with pytest.raises(DatabaseMaintenanceError) as failure:
        service.flush()
    assert 'private reset refusal' not in str(failure.value)
    assert (service.counts(), gateway.database.run(source_fingerprint)) == before
    assert len(list(tmp_path.glob('*.dump'))) == 2


@pytest.mark.parametrize('malformed', [False, True])
def test_default_seed_requires_native_schema_and_never_treats_damage_as_empty(empty_database, tmp_path, malformed):
    if malformed:
        with psycopg.connect(empty_database.operator_url) as connection:
            connection.execute('CREATE SCHEMA eppm')
            connection.execute('CREATE TABLE eppm.database_identity(unexpected text)')
            connection.execute("INSERT INTO eppm.database_identity VALUES ('Preserved sentinel')")
    service = MaintenanceService(PostgresMaintenanceGateway(empty_database.operator_url, tmp_path))
    with pytest.raises(DatabaseMaintenanceError):
        service.seed_defaults()
    assert list(tmp_path.iterdir()) == []
    with psycopg.connect(empty_database.operator_url) as connection:
        tables = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='eppm'").fetchall()
        assert tables == ([('database_identity',)] if malformed else [])
        if malformed:
            assert connection.execute('SELECT * FROM eppm.database_identity').fetchall() == [('Preserved sentinel',)]


def test_unavailable_operator_database_exposes_only_safe_maintenance_errors(tmp_path, caplog):
    # A bound, non-listening local socket provides a real refused connection.
    with socket.socket() as unavailable:
        unavailable.bind(('127.0.0.1', 0))
        port = unavailable.getsockname()[1]
        url = f'postgresql://operator:private-diagnostic-only@127.0.0.1:{port}/isolated'
        service = MaintenanceService(PostgresMaintenanceGateway(url, tmp_path))
        with pytest.raises(DatabaseMaintenanceError) as failure:
            service.counts()
    assert 'private-diagnostic-only' not in str(failure.value) + caplog.text
    assert str(port) not in str(failure.value) + caplog.text
    assert list(tmp_path.iterdir()) == []
