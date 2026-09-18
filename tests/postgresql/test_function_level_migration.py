"""Remove numeric classification while retaining parent links and CSV identities."""

from dataclasses import asdict

import psycopg
import pytest

from app.domain.organization.models import OrgFunction
from app.infrastructure.postgresql.migration import check_schema, discover_migrations, migrate
from tests.postgresql.test_organization import organization


def test_upgrade_removes_level_and_preserves_parent_links_and_memberships(empty_database, tmp_path):
    migrations = discover_migrations()
    for migration in migrations[:59]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level,manager_function_id) VALUES (1,'Root',7,NULL),(2,'Child',2,1)")
        connection.execute("INSERT INTO eppm.team(team_id,team_name) VALUES (1,'Team')")
        connection.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES (1,2)')
        before = connection.execute("SELECT to_jsonb(f)-'hierarchy_level' FROM eppm.function f ORDER BY function_id").fetchall()
    assert migrate(empty_database.operator_url) == tuple(item.name for item in migrations[59:])
    with psycopg.connect(empty_database.operator_url) as connection:
        check_schema(connection)
        assert connection.execute('SELECT to_jsonb(f) FROM eppm.function f ORDER BY function_id').fetchall() == before
        assert connection.execute('SELECT team_id,function_id FROM eppm.active_team_function').fetchall() == [(1, 2)]
        assert connection.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='eppm' AND table_name IN ('function','active_function') AND column_name='hierarchy_level'").fetchone() == (0,)
    assert migrate(empty_database.operator_url) == ()


def test_csv_round_trip_preserves_parents_and_rejects_obsolete_headers(organization):
    root = organization.create_function(OrgFunction('Root'))
    child = organization.create_function(OrgFunction('Child', manager_function_id=root))
    content = organization.export_csv('functions')
    assert 'hierarchy_level' not in content.splitlines()[0]
    assert organization.export_csv('functions', template=True).splitlines() == [content.splitlines()[0]]
    result = organization.import_functions_csv(content.encode())
    assert (result.created, result.updated, result.deleted) == (0, 2, 0)
    assert organization.get_function_by_id(child).manager_function_id == root
    with pytest.raises(ValueError, match='Unsupported CSV columns: hierarchy_level'):
        organization.import_functions_csv(f'function_id,name,manager_function_id,hierarchy_level\n{child},Renamed,{root},3\n'.encode())
    record = organization.get_function_by_id(child)
    assert record.name == 'Child' and record.manager_function_id == root
    assert 'hierarchy_level' not in asdict(record)
