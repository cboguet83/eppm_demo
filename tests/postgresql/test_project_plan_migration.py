"""Upgrade populated schedules without changing current business data."""

import psycopg

from app.infrastructure.postgresql.migration import discover_migrations, migrate, check_schema


def test_existing_schedule_becomes_approved_current_with_primary_link_and_tags(empty_database, tmp_path):
    for migration in discover_migrations()[:40]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES('General',true)")
        connection.execute("INSERT INTO eppm.project(name) VALUES('Existing')")
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,progress_pct) VALUES(1,1,'First','2027-01-01','2027-01-02',65),(2,1,'Second','2027-01-03','2027-01-04',NULL)")
        connection.execute('UPDATE eppm.project_task SET predecessor_id=1 WHERE id=2')
        connection.execute("INSERT INTO eppm.task_tag(task_id,free_tag) VALUES(2,'Critical')")
    assert len(migrate(empty_database.operator_url)) == 3
    with psycopg.connect(empty_database.operator_url) as connection:
        check_schema(connection)
        status, current, baseline, content = connection.execute('''SELECT status_id,is_current,is_baseline,content
            FROM eppm.project_plan WHERE project_id=1''').fetchone()
        assert (status, current, baseline) == (3, True, False)
        assert len(content['tasks']) == 2
        assert content['dependencies'][0]['predecessor_task_id'] == 1
        assert content['task_tags']['2'] == [{'tag_id': None, 'free_tag': 'Critical'}]
        assert connection.execute('SELECT progress_pct FROM eppm.plan_task_actual ORDER BY task_id').fetchall() == [(65,), (0,)]
    assert migrate(empty_database.operator_url) == ()
