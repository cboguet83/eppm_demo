"""Complete explicit maintenance port with no runtime initialization side effects."""

from dataclasses import replace

import psycopg
import pytest

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
    assert before['projects'] == 5 and before['pools'] == 103
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


@pytest.mark.parametrize('operation', ['startup', 'projects', 'allocations', 'scenarios'])
def test_invalid_requests_fail_before_operator_connection_or_archive(tmp_path, monkeypatch, operation):
    def unexpected_connection(*args, **kwargs):
        pytest.fail('Invalid options must fail before opening a database connection.')
    monkeypatch.setattr(psycopg, 'connect', unexpected_connection)
    service = MaintenanceService(PostgresMaintenanceGateway('postgresql://operator@localhost/example', tmp_path))
    with pytest.raises(ValueError):
        if operation == 'startup':
            service.startup(projects=-1)
        elif operation == 'projects':
            service.seed_projects(SeedRequest(projects=-1))
        elif operation == 'allocations':
            service.generate_pool_allocations(replace(AllocationGenerationRequest(), allocated_pools_pct=-1), apply=True)
        else:
            service.seed_pool_scenarios(year=0, apply=True)
    assert list(tmp_path.iterdir()) == []
