"""Upgrade preserves native priorities and retires obsolete project fields."""

import psycopg
import pytest

from app.infrastructure.postgresql.migration import check_schema, discover_migrations, migrate


@pytest.mark.parametrize('unknown', [False, True])
def test_priority_upgrade_is_atomic_and_preserves_assignments(empty_database, tmp_path, unknown):
    migrations = discover_migrations()
    for migration in migrations[:62]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(id,name,is_general) VALUES(1,'General',true)")
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES ('PRM_027','strategic_priority','ENUM')")
        connection.execute("INSERT INTO eppm.project(id,name,planned_budget,actual_budget) VALUES (1,'Strategic project',1,2),(2,'Unassigned',3,4)")
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) VALUES (1,'PRM_027','text',%s)", ('Unknown' if unknown else 'Critical',))
    if unknown:
        with pytest.raises(ValueError, match='Unknown PRM_027'):
            migrate(empty_database.operator_url)
        with psycopg.connect(empty_database.operator_url) as connection:
            assert connection.execute('SELECT planned_budget,actual_budget FROM eppm.project WHERE id=1').fetchone() == (1, 2)
            assert connection.execute('SELECT max(version) FROM eppm.schema_migration').fetchone() == (62,)
        return
    assert migrate(empty_database.operator_url) == tuple(item.name for item in migrations[62:])
    with psycopg.connect(empty_database.operator_url) as connection:
        check_schema(connection)
        assert connection.execute('SELECT strategic_priority_id FROM eppm.project ORDER BY id').fetchall() == [(1,), (None,)]
        assert connection.execute("SELECT count(*) FROM eppm.schema_parameters WHERE param_id='PRM_027'").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='eppm' AND table_name='project' AND column_name IN ('planned_budget','actual_budget')").fetchone() == (0,)
    assert migrate(empty_database.operator_url) == ()
