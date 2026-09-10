"""Dependency-filter traversal stays scoped and avoids repeated graph scans."""

from contextlib import closing

import pytest

from app.infrastructure.database.connection import get_db
from app.main import create_planning_service
from tests.test_business_transaction_security import business as business


def test_dependency_closure_does_not_rescan_unrelated_tasks_for_each_connected_project(business):
    path, _, _, _, administrator = business
    with closing(get_db(path)) as connection, connection:
        connection.executemany("INSERT INTO project(id,name) VALUES(?,?)", [(i, f"Connected {i}") for i in range(3, 12)])
        connection.executemany(
            "INSERT INTO project_task(id,project_id,task_name,start_date,end_date) VALUES(?,?,?,'2026-01-01','2026-01-02')",
            [(i * 10, i, "Connected task") for i in range(3, 12)]
            + [(i, 2, "Unrelated task") for i in range(1000, 6000)],
        )
        connection.executemany(
            "INSERT INTO task_dependencies(task_id,predecessor_task_id) VALUES(?,?)",
            [(i, i - 1) for i in range(1001, 6000)],
        )
    service = create_planning_service(path, access=administrator)

    def measured_closure() -> tuple[list[int], int]:
        with service._gateway.transaction() as store:
            instructions = 0

            def count() -> int:
                nonlocal instructions
                instructions += 1
                return 0

            store.connection.set_progress_handler(count, 100)
            try:
                result = store.related_project_ids(1, "all")
            finally:
                store.connection.set_progress_handler(None, 0)
            return result, instructions

    original, before = measured_closure()
    with closing(get_db(path)) as connection, connection:
        connection.executemany(
            "INSERT INTO task_dependencies(task_id,predecessor_task_id) VALUES(?,?)",
            [(i * 10, (i - 1) * 10) for i in range(3, 12)],
        )
    connected, after = measured_closure()

    assert original == [1, 2]
    assert connected == list(range(1, 12))
    assert after < before * 1.5


@pytest.mark.parametrize("scope,expected", [("this", [1]), ("predecessors", [1, 3]), ("all", [1, 3, 4])])
def test_dependency_filters_follow_visible_task_project_and_legacy_links_without_crossing_hidden_projects(business, scope, expected):
    path, access, administrator, editor, _ = business
    with closing(get_db(path)) as connection, connection:
        connection.executemany("INSERT INTO project(id,name) VALUES(?,?)", [(i, f"Project {i}") for i in range(3, 6)])
        connection.executemany(
            "INSERT INTO project_task(id,project_id,task_name,start_date,end_date) VALUES(?,?,?,'2026-01-01','2026-01-02')",
            [(i * 10, i, "Task") for i in range(3, 6)],
        )
        connection.execute("INSERT INTO task_dependencies(task_id,predecessor_project_id) VALUES(10,3)")
        connection.execute("UPDATE project_task SET predecessor_id=10 WHERE id=40")
        connection.execute("INSERT INTO task_dependencies(task_id,predecessor_task_id) VALUES(20,50)")
    access.grant(administrator, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [3, 4, 5]})
    service = create_planning_service(path, access=editor)

    assert service.related_project_ids(1, scope) == expected
    if scope == "all":
        assert service.related_project_ids([1, 1, 5], scope) == [1, 3, 4, 5]
