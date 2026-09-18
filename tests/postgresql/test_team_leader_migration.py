"""Remove leadership without transferring roles or explicit memberships."""

import psycopg

from app.infrastructure.postgresql.migration import check_schema, discover_migrations, migrate


def test_remove_leader_preserves_manager_membership_and_invalidates_capacity(empty_database, tmp_path):
    for migration in discover_migrations()[:50]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level) VALUES (1,'Manager',1),(2,'Leader',2)")
        connection.execute("INSERT INTO eppm.team(team_id,team_name,manager_function_id,leader_function_id) VALUES (1,'Leader only',NULL,2),(2,'Both',1,2)")
        connection.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES (2,2)')
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES (1,'Mapped team',1)")
        connection.execute("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) VALUES (1,'team',1,100)")
        assert connection.execute('SELECT function_id FROM eppm.capacity_contributions(ARRAY[1]::bigint[])').fetchall() == [(2,)]
        revision = connection.execute('SELECT revision FROM eppm.catalog_cache_revision').fetchone()[0]

    assert migrate(empty_database.operator_url) == tuple(item.name for item in discover_migrations()[50:])
    with psycopg.connect(empty_database.operator_url) as connection:
        check_schema(connection)
        assert connection.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='eppm' AND table_name='team' AND column_name='leader_function_id'").fetchone() == (0,)
        assert connection.execute('SELECT team_id,manager_function_id FROM eppm.team ORDER BY team_id').fetchall() == [(1, None), (2, 1)]
        assert connection.execute('SELECT team_id,function_id FROM eppm.team_function').fetchall() == [(2, 2)]
        assert connection.execute('SELECT count(*) FROM eppm.function').fetchone() == (2,)
        assert connection.execute('SELECT function_id FROM eppm.capacity_contributions(ARRAY[1]::bigint[])').fetchall() == []
        # Subsequent migrations also refresh projections and invalidate catalogs.
        assert connection.execute('SELECT revision FROM eppm.catalog_cache_revision').fetchone()[0] > revision
    assert migrate(empty_database.operator_url) == ()
