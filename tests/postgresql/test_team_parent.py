"""Parent-team persistence, integrity, concurrency, and Settings workflows."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import psycopg
import pytest

from app.application.exceptions import OrganizationConflictError
from app.domain.organization.models import Team
from app.main import create_organization_service
from app.infrastructure.postgresql.migration import discover_migrations, migrate
from tests.postgresql.test_organization import organization, simultaneous_gateways
from tests.postgresql.test_organization_ui import access, database, dialog, button


def test_upgrade_preserves_existing_teams_as_roots(empty_database, tmp_path):
    migrations = discover_migrations()
    for migration in migrations[:37]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        team_id = connection.execute(
            "INSERT INTO eppm.team(team_name) VALUES ('Existing team') RETURNING team_id"
        ).fetchone()[0]
    assert migrate(empty_database.operator_url) == tuple(item.name for item in migrations[37:])
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute(
            'SELECT team_name,parent_team_id FROM eppm.team WHERE team_id=%s', (team_id,)
        ).fetchone() == ('Existing team', None)


def test_parent_links_can_be_assigned_reparented_and_cleared(organization):
    roots = [organization.create_team(Team(name)) for name in ('Root', 'Other')]
    child_id = organization.create_team(Team('Child', parent_team_id=roots[0]))
    child = organization.get_team_by_id(child_id)
    assert child.parent_team_id == roots[0]
    assert organization.get_all_teams()[0].parent_team_id == roots[0]
    with pytest.raises(OrganizationConflictError):
        organization.delete_team(roots[0])
    assert organization.update_team(replace(child, parent_team_id=roots[1]))
    assert organization.get_team_by_id(child_id).parent_team_id == roots[1]
    assert organization.delete_team(roots[0])
    assert organization.update_team(replace(child, parent_team_id=None))
    assert organization.delete_team(roots[1])
    assert organization.get_team_by_id(child_id).parent_team_id is None


def test_database_rejects_missing_parent_self_parent_and_multi_team_cycles(authorized, organization):
    root = organization.create_team(Team('Root'))
    child = organization.create_team(Team('Child', parent_team_id=root))
    leaf = organization.create_team(Team('Leaf', parent_team_id=child))
    for target, parent, error in [(root, 999999, psycopg.errors.ForeignKeyViolation),
                                  (root, root, psycopg.errors.CheckViolation),
                                  (root, leaf, psycopg.errors.CheckViolation)]:
        with psycopg.connect(authorized.setup.operator_url) as connection:
            with pytest.raises(error):
                connection.execute('UPDATE eppm.team SET parent_team_id=%s WHERE team_id=%s', (parent, target))
    assert organization.get_team_by_id(root).parent_team_id is None
    with pytest.raises(ValueError, match='circular'):
        organization.update_team(Team('Root', team_id=root, parent_team_id=leaf))
    with pytest.raises(ValueError, match='no longer exists'):
        organization.create_team(Team('Missing', parent_team_id=999999))


def test_concurrent_opposite_parent_links_cannot_commit_a_cycle(organization, authorized):
    first, second = [organization.create_team(Team(name)) for name in ('First', 'Second')]
    services, _ = simultaneous_gateways(authorized)

    def link(index, child, parent):
        try:
            return services[index].update_team(Team(str(child), team_id=child, parent_team_id=parent))
        except (ValueError, OrganizationConflictError):
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(link, 0, first, second), executor.submit(link, 1, second, first)]
        assert sorted(future.result(timeout=20) for future in futures) == [False, True]
    assert sum(team.parent_team_id is not None for team in organization.get_all_teams()) == 1


def test_settings_create_change_and_clear_parent(database, access):
    service = create_organization_service(database, access=access)
    root = service.create_team(Team('Root'))
    other = service.create_team(Team('Other'))
    app = dialog(database, access, '_open_add_team_dialog(service, functions)')
    app.text_input[0].input('Child')
    app.selectbox(key='parent_team_new').set_value(root)
    button(app, 'Save').click().run()
    assert not app.exception
    child = next(team for team in service.get_all_teams() if team.team_name == 'Child')
    assert child.parent_team_id == root
    for parent in (other, None):
        app = dialog(database, access, f'_open_edit_team_dialog(service, {child.team_id}, functions)')
        app.selectbox(key=f'parent_team_{child.team_id}').set_value(parent or 0)
        button(app, 'Save').click().run()
        assert not app.exception
        assert service.get_team_by_id(child.team_id).parent_team_id == parent
