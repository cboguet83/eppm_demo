"""Independent project title saves must survive a concurrent editor workload."""

from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier, Lock

import psycopg
import pytest

from app.application.ports.maintenance import SeedRequest
from app.application.services.access import AuthorizationPolicy, SessionLimits
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor
from app.infrastructure.postgresql.bulk_seed import generate_projects
from app.infrastructure.postgresql.pool import Database, OperatorDatabase
from app.infrastructure.postgresql.projects import PostgresProjectStore
from app.main import create_project_service, create_project_workspace
from app.presentation.components.portfolio_project_dialog import ProjectDraft, _accept_values, _project_form, _property_values
from app.presentation.components.project_dialogs import _dialog_references
from app.runtime import RuntimeResources
from app.shared.config.database import DatabaseConfig


@pytest.mark.parametrize("legacy_scope", [False, True], ids=["scalar-scope", "legacy-unnest"])
def test_scope_resolution_during_query_planning_is_removed(authorized, record_property, legacy_scope):
    OperatorDatabase(authorized.setup.operator_url).run(
        lambda connection: generate_projects(connection, SeedRequest(
            projects=10, min_tasks=0, max_tasks=15, clean_first=True, random_seed=42), year=2026),
        write=True,
    )
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("ANALYZE eppm.project")
        if legacy_scope:
            connection.execute("ALTER POLICY business_select ON eppm.project USING ("
                               "(SELECT eppm.has_global_permission('project.read')) OR "
                               "id IN (SELECT unnest(eppm.permission_projects('project.read'))))")

    def inspect_planning(connection):
        # No ANALYZE: this query is planned, never executed. A project predicate
        # can therefore only come from evaluating the stable scope for estimates.
        plan = connection.execute("EXPLAIN (FORMAT JSON) SELECT id FROM eppm.project WHERE id=%s", (4,)).fetchone()[0]
        locks = connection.execute("SELECT locktype FROM pg_locks WHERE pid=pg_backend_pid() "
                                   "AND mode='SIReadLock' AND relation='eppm.project'::regclass").fetchall()
        return plan, locks

    plan, locks = authorized.database.run(inspect_planning, write=True, bind=authorized.binding(4))
    record_property("plan", json.dumps(plan))
    record_property("project_predicates", json.dumps(locks))
    assert locks == ([("relation",)] if legacy_scope else [])


@pytest.mark.parametrize("project_count,payload_kind,scope_kind", [
    (10, "stored", "all"), (10, "stored", "projects"),
    (10, "browser-form", "all"), (10, "browser-form", "projects"),
    (10001, "browser-form", "all"),
])
def test_ten_distinct_editors_can_save_independent_project_titles(
    authorized, monkeypatch, record_property, scope_kind, payload_kind, project_count,
):
    OperatorDatabase(authorized.setup.operator_url).run(
        lambda connection: generate_projects(connection, SeedRequest(
            projects=project_count, min_tasks=0, max_tasks=15, clean_first=True, random_seed=42), year=2026),
        write=True,
    )
    with psycopg.connect(authorized.setup.operator_url) as connection:
        project_ids = [row[0] for row in connection.execute("SELECT id FROM eppm.project ORDER BY id LIMIT 10")]
        for index in range(10):
            user_id = 100 + index
            connection.execute("INSERT INTO eppm.app_user(id,status,created_at,updated_at) VALUES(%s,'active',900,900)", (user_id,))
            connection.execute("INSERT INTO eppm.app_session VALUES(%s,%s,950,2000,980,false,false)",
                               (f"editor-{user_id}", user_id))
            scope = {"kind": scope_kind}
            if scope_kind == "projects":
                scope["project_ids"] = [project_ids[index]]
            connection.execute("INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by) "
                               "VALUES(%s,'project_editor',%s::jsonb,900,'test setup')", (user_id, json.dumps(scope)))
        connection.execute("ANALYZE eppm.project")
        connection.execute("ANALYZE eppm.project_property_value")
        connection.execute("ANALYZE eppm.app_role_assignment")
    database = Database(DatabaseConfig(authorized.setup.runtime_url, pool_min=10, pool_max=10))
    database.open()
    try:
        resources = RuntimeResources(database, authorized.key)
        accesses = [BusinessAccess(
            Actor(100 + index, f"editor-{100 + index}", f"title-{index}"),
            AuthorizationPolicy(lambda: 1000, SessionLimits()),
        ) for index in range(10)]
        services = [create_project_service(resources, access=access) for access in accesses]
        projects = [service.get_project_by_id(project_id) for service, project_id in zip(services, project_ids)]
        properties = [project.dynamic_attributes for project in projects]
        if payload_kind == "browser-form":
            properties = []
            for index, project in enumerate(projects):
                workspace = create_project_workspace(resources, access=accesses[index])
                draft = ProjectDraft(project.id, project, _dialog_references(workspace))
                draft.form = _project_form(workspace, draft, project.project_type_id)
                values = dict(draft.form["values"])
                for field in draft.form["fields"]:
                    if field["kind"] not in {"multi", "tags"}:
                        value = values[field["key"]]
                        values[field["key"]] = "" if value is None else str(value)
                values["name"] = f"Concurrent title {index}"
                _accept_values(draft, {"values": values, "dirty": ["name"], "links": [], "wbs": []})
                properties.append(_property_values(draft, values))
            assert all(value == project.dynamic_attributes.get(key)
                       for project, values in zip(projects, properties) for key, value in values.items())
        attempts = dict.fromkeys(project_ids, 0)
        backends = set()
        lock = Lock()
        predicates = []

        def inspect_predicates():
            with psycopg.connect(authorized.setup.operator_url) as connection:
                predicates.extend(connection.execute("SELECT relation::regclass::text,locktype,count(*) "
                    "FROM pg_locks WHERE pid=ANY(%s) AND mode='SIReadLock' GROUP BY 1,2 ORDER BY 1,2",
                    (list(backends),)).fetchall())

        barrier = Barrier(10, action=inspect_predicates, timeout=15)
        original_find = PostgresProjectStore.find

        def coordinated_find(store, project_id):
            project = original_find(store, project_id)
            with lock:
                attempts[project_id] += 1
                first = attempts[project_id] == 1
                backends.add(store.connection.info.backend_pid)
            if first:
                barrier.wait()
            return project

        monkeypatch.setattr(PostgresProjectStore, "find", coordinated_find)

        def save(index):
            project = projects[index]
            return services[index].update_project(
                project_id=project.id, name=f"Concurrent title {index}", status=project.status,
                dynamic_attributes=properties[index], function_id=project.function_id,
                strategic_priority_id=project.strategic_priority_id,
                project_type_id=project.project_type_id, custom_links=[], wbs_allocations=[],
            )

        errors = []
        results = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(save, index) for index in range(10)]
            for index, future in enumerate(futures):
                try:
                    results.append(future.result())
                except Exception as error:
                    errors.append((index, type(error).__name__, str(error)))
        record_property("attempts", json.dumps(attempts))
        record_property("predicate_locks", json.dumps(predicates))
        assert not errors, errors
        assert all(result is True for result in results), results
        with psycopg.connect(authorized.setup.operator_url) as connection:
            assert connection.execute("SELECT id,name FROM eppm.project WHERE id=ANY(%s) ORDER BY id",
                                      (project_ids,)).fetchall() == [
                (project_id, f"Concurrent title {index}") for index, project_id in enumerate(project_ids)]
    finally:
        database.close()
