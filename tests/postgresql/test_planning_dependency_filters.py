"""Dependency-filter traversal stays scoped and avoids repeated graph scans."""

import psycopg

import pytest

from app.main import create_planning_service
from tests.postgresql.business import business


def test_dependency_closure_does_not_rescan_unrelated_tasks_for_each_connected_project(pg_database, business, monkeypatch, record_property):
    path, _, _, _, administrator = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.cursor().executemany("INSERT INTO eppm.project(id,name) VALUES(%s,%s)", [(i, f"Connected {i}") for i in range(3, 12)])
        connection.execute("""INSERT INTO eppm.project_plan(project_id,version,name,status_id,is_current,author,created_at)
            SELECT id,1,'Initial plan',3,true,'test',CURRENT_TIMESTAMP FROM eppm.project WHERE id>=3""")
        connection.cursor().executemany(
            "INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES(%s,%s,%s,'2026-01-01','2026-01-02',(SELECT id FROM eppm.project_plan WHERE project_id=%s AND is_current))",
            [(i * 10, i, "Connected task", i) for i in range(3, 12)]
            + [(i, 2, "Unrelated task", 2) for i in range(1000, 6000)],
        )
        connection.cursor().executemany(
            "INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES(%s,%s)",
            [(i, i - 1) for i in range(1001, 6000)],
        )
    service = create_planning_service(path, access=administrator)

    original_execute = psycopg.Connection.execute

    def measured_closure() -> tuple[list[int], int]:
        plans = []

        def observe(connection, query, params=None, **kwargs):
            # Observe the real service query on its actual restricted, actor-bound
            # connection. EXPLAIN ANALYZE executes the same read-only SQL; no
            # query result or database authorization behavior is substituted.
            if isinstance(query, str) and query.startswith("WITH RECURSIVE legacy AS MATERIALIZED"):
                plan = original_execute(connection, "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, params).fetchone()[0][0]["Plan"]
                plans.append(plan)
            return original_execute(connection, query, params, **kwargs)

        with psycopg.connect(pg_database.operator_url) as connection:
            for table in ("project", "project_task", "task_dependencies"):
                connection.execute("ANALYZE eppm." + table)
        with monkeypatch.context() as observation:
            observation.setattr(psycopg.Connection, "execute", observe)
            result = service.related_project_ids(1, "all")
        assert len(plans) == 1
        plan = plans[0]
        return result, plan["Shared Hit Blocks"] + plan["Shared Read Blocks"]

    original, before = measured_closure()
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.cursor().executemany(
            "INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES(%s,%s)",
            [(i * 10, (i - 1) * 10) for i in range(3, 12)],
        )
    connected, after = measured_closure()

    assert original == [1, 2]
    assert connected == list(range(1, 12))
    record_property("two_project_shared_blocks", before)
    record_property("eleven_project_shared_blocks", after)
    assert after < before * 1.5, (before, after)


@pytest.mark.parametrize("scope,expected", [("this", [1]), ("predecessors", [1, 3]), ("all", [1, 3, 4])])
def test_dependency_filters_follow_visible_task_project_and_legacy_links_without_crossing_hidden_projects(pg_database, business, scope, expected):
    path, access, administrator, editor, _ = business
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.cursor().executemany("INSERT INTO eppm.project(id,name) VALUES(%s,%s)", [(i, f"Project {i}") for i in range(3, 6)])
        connection.execute("""INSERT INTO eppm.project_plan(project_id,version,name,status_id,is_current,author,created_at)
            SELECT id,1,'Initial plan',3,true,'test',CURRENT_TIMESTAMP FROM eppm.project WHERE id>=3""")
        connection.cursor().executemany(
            "INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES(%s,%s,%s,'2026-01-01','2026-01-02',(SELECT id FROM eppm.project_plan WHERE project_id=%s AND is_current))",
            [(i * 10, i, "Task", i) for i in range(3, 6)],
        )
        connection.execute("INSERT INTO eppm.task_dependencies(task_id,predecessor_project_id) VALUES(10,3)")
        connection.execute("UPDATE eppm.project_task SET predecessor_id=10 WHERE id=40")
        connection.execute("INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES(20,50)")
    access.grant(administrator, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [3, 4, 5]})
    service = create_planning_service(path, access=editor)

    assert service.related_project_ids(1, scope) == expected
    if scope == "all":
        assert service.related_project_ids([1, 1, 5], scope) == [1, 3, 4, 5]
