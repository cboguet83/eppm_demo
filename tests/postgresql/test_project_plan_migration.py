"""Upgrade populated schedules without changing current business data."""

import psycopg
from psycopg.types.json import Jsonb

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
    assert migrate(empty_database.operator_url) == tuple(item.name for item in discover_migrations()[40:])
    with psycopg.connect(empty_database.operator_url) as connection:
        check_schema(connection)
        from app.infrastructure.postgresql.plan_rows import read_plans
        identity, status, current, baseline = connection.execute('''SELECT id,status_id,is_current,is_baseline
            FROM eppm.project_plan WHERE project_id=1 AND is_current''').fetchone()
        content = read_plans(connection, [identity])[identity]
        assert (status, current, baseline) == (3, True, False)
        assert len(content.tasks) == 2
        assert content.dependencies[0]['predecessor_task_id'] == 1
        assert content.task_tags[2] == [{'tag_id': None, 'free_tag': 'Critical'}]
        assert [task['progress_pct'] for task in content.tasks] == [65, 0]
        assert connection.execute("SELECT to_regclass('eppm.plan_task_actual')").fetchone() == (None,)
    assert migrate(empty_database.operator_url) == ()


def test_relational_upgrade_preserves_divergent_live_work_baseline_and_identity_high_water(empty_database, tmp_path):
    for migration in discover_migrations()[:44]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    historical = dict(tasks=[dict(id=9000, task_name='Baseline task', phase='General',
        start_date='2027-01-01', end_date='2027-01-02', description='')],
        dependencies=[], assignments=[], task_tags={})
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES('General',true)")
        connection.execute("INSERT INTO eppm.project(name) VALUES('Existing')")
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,progress_pct) VALUES(5,1,'Unsaved live edit','2027-02-01','2027-02-02',30)")
        connection.execute("SELECT setval('eppm.project_task_id_seq',10001)")
        connection.execute('''INSERT INTO eppm.project_plan
            (project_id,version,name,status_id,is_current,is_baseline,author,created_at,content)
            VALUES(1,1,'Old baseline',3,true,true,'test',CURRENT_TIMESTAMP,%s)''', (Jsonb(historical),))
    migrate(empty_database.operator_url)
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute('SELECT id,task_name,start_date::text,progress_pct FROM eppm.current_project_task').fetchall() == [
            (5, 'Unsaved live edit', '2027-02-01', 30)]
        assert connection.execute('''SELECT t.stable_task_id,t.task_name,p.is_current,p.is_frozen
            FROM eppm.project_task t JOIN eppm.project_plan p ON p.id=t.project_plan_id WHERE p.is_baseline''').fetchall() == [
            (9000, 'Baseline task', False, True)]
        assert connection.execute("SELECT nextval('eppm.project_task_id_seq')").fetchone()[0] > 10001
        assert connection.execute('SELECT count(*) FROM eppm.project_plan').fetchone() == (2,)


def test_retiring_actual_mirror_preserves_each_plan_task_progress(empty_database, tmp_path):
    for migration in discover_migrations()[:46]:
        (tmp_path / migration.name).write_bytes(migration.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES('General',true)")
        connection.execute("INSERT INTO eppm.project(name) VALUES('Progress versions')")
        connection.execute("""INSERT INTO eppm.project_plan(project_id,version,name,status_id,is_current,is_baseline,is_frozen,author,created_at)
            VALUES(1,1,'Current',3,true,false,false,'test',CURRENT_TIMESTAMP),
                  (1,2,'Baseline',3,false,true,true,'test',CURRENT_TIMESTAMP),
                  (1,3,'Alternative',2,false,false,false,'test',CURRENT_TIMESTAMP)""")
        connection.execute("""INSERT INTO eppm.project_task(project_id,project_plan_id,stable_task_id,task_name,start_date,end_date,progress_pct)
            VALUES(1,1,1,'Task','2027-01-01','2027-01-02',65),
                  (1,2,1,'Task','2027-01-01','2027-01-02',20),
                  (1,3,1,'Task','2027-01-01','2027-01-02',90)""")
        connection.execute('INSERT INTO eppm.plan_task_actual VALUES(1,1,65)')
        before = connection.execute('SELECT * FROM eppm.project_task ORDER BY id').fetchall()
    assert migrate(empty_database.operator_url) == tuple(item.name for item in discover_migrations()[46:])
    with psycopg.connect(empty_database.operator_url) as connection:
        check_schema(connection)
        assert connection.execute('SELECT * FROM eppm.project_task ORDER BY id').fetchall() == before
        assert connection.execute("SELECT to_regclass('eppm.plan_task_actual')").fetchone() == (None,)
