"""Team catalog imports, source integrity and shared administration projection."""

import csv
from datetime import date
from io import StringIO

import psycopg
import pytest

from app.application.services.organization import OrganizationService
from app.domain.access.models import AccessDenied
from app.domain.organization.models import Team
from app.infrastructure.postgresql.organization import PostgresOrganizationGateway
from tests.postgresql.test_resource_soft_deletion import mapped_team


def service(setup, user_id=4):
    return OrganizationService(PostgresOrganizationGateway(setup.database, setup.key, access=setup.binding(user_id).access))


def test_team_overview_current_capacity_future_flags_allocations_and_deleted_resources(mapped_team):
    org = service(mapped_team)
    overview = org.team_overview(today=date(2026, 1, 2))
    assert overview.capacities[1].current_fte == .5
    assert overview.capacities[1].has_future_exceptions
    assert overview.pool_mappings == [{'team_id': 1, 'pool_id': 1, 'pool_name': 'Mapped', 'allocation_pct': 100}]
    org.delete_employee(1)
    detail = org.team_overview(today=date(2026, 1, 2)).capacities[1]
    assert detail.current_fte == 0 and not detail.has_employees and not detail.exceptions
    assert len(detail.members) == 1 and detail.members[0].employee_id is None
    org.delete_team(1)
    assert org.team_overview().teams == []
    overview = org.team_overview(include_deleted=True)
    assert overview.teams[0].deleted_flag and overview.pool_mappings == []
    assert org.undelete_team(1)
    assert org.get_all_teams()[0].team_id == 1


def test_team_import_keeps_missing_by_default_and_can_soft_delete_them(mapped_team):
    org = service(mapped_team)
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        connection.execute("SELECT setval(pg_get_serial_sequence('eppm.team','team_id'),1)")
    result = org.import_teams_csv(b'team_id,team_name,parent_team_id\n9999,New child,8888\n8888,New parent,\n')
    assert (result.created, result.updated, result.deleted) == (2, 0, 0)
    teams = {team.team_name: team for team in org.get_all_teams()}
    assert teams['New child'].parent_team_id == teams['New parent'].team_id
    assert {team.team_id for team in teams.values()} == {1, 2, 3}
    assert org.get_team_functions(1) == [1]
    result = org.import_teams_csv(b'team_id,team_name\n1,Updated\n', delete_missing=True)
    assert result.deleted == 2 and len(org.get_all_teams()) == 1
    assert len(list(csv.DictReader(StringIO(org.export_csv('teams', include_deleted=True))))) == 3
    assert len(list(csv.DictReader(StringIO(org.export_csv('teams'))))) == 1
    assert org.get_team_functions(1) == [1]
    assert len(org.team_overview().pool_mappings) == 1


def test_invalid_team_import_rolls_back_updates_and_creations(mapped_team):
    org = service(mapped_team)
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        connection.execute("SELECT setval(pg_get_serial_sequence('eppm.team','team_id'),1)")
    before = org.export_csv('teams', include_deleted=True)
    with pytest.raises(ValueError, match='circular'):
        org.import_teams_csv(b'team_id,team_name,parent_team_id\n1,Changed,9999\n9999,New,1\n')
    assert org.export_csv('teams', include_deleted=True) == before
    with pytest.raises(AccessDenied):
        service(mapped_team, 2).import_teams_csv(b'team_name\nDenied\n')


def test_restoring_team_requires_live_parent(mapped_team):
    org = service(mapped_team)
    with psycopg.connect(mapped_team.setup.operator_url) as connection:
        connection.execute("SELECT setval(pg_get_serial_sequence('eppm.team','team_id'),1)")
    child = org.create_team(Team('Child', parent_team_id=1))
    org.delete_team(child)
    org.delete_team(1)
    with pytest.raises(ValueError, match='parent team'):
        org.undelete_team(child)
    assert org.undelete_team(1) and org.undelete_team(child)
