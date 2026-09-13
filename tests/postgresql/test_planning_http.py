"""Actual authenticated HTTP task batches preserve scope and reject stale delivery."""


import psycopg
import pytest

from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Permission, VerifiedIdentity
from app.infrastructure.authentication.http import SESSION_COOKIE
from app.infrastructure.authentication.planning import PlanningReadRoutes
from app.main import create_planning_workspace
from app.presentation.components import planning_transport
from tests.postgresql.test_session_transport import transport as transport
from tests.postgresql.test_dashboard_ui import business as business, runtime as runtime


@pytest.fixture
def task_browser(pg_database, transport):
    browser, service, admin, _, settings, _, resources = transport
    service.grant(admin, admin.user_id, "business_admin", {"kind": "all"})
    cookie = service.sign_in(VerifiedIdentity(settings.issuer, "scoped-reader", "", "Reader", 1000, 100000, True))
    actor = service.actor(cookie)
    service.set_status(admin, actor.user_id, "active")
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(id,name) VALUES(1,'Visible'),(2,'Hidden')")
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date) VALUES(10,1,'Visible task','2026-01-01','2026-01-05'),(20,2,'Hidden task','2026-01-01','2026-01-05')")
        connection.execute("INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id,link_type,lag_days) VALUES(10,20,'FS',0)")
    assignment = service.grant(admin, actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [1]})

    def read_tasks(current_actor, ids, revision, *, source_tokens=None):
        access = BusinessAccess(current_actor, service.policy)
        service.gateway.run(lambda store: access.require(store, Permission.READ, ids), actor=current_actor)
        workspace = create_planning_workspace(resources, access=access)
        return planning_transport.read_planning_batch(workspace, ids, revision, source_tokens=source_tokens)

    browser.app.router.routes.extend(PlanningReadRoutes(service, read_tasks,
        read_task_sources=lambda actor, ids, sources: read_tasks(actor, ids, '', source_tokens=sources)).routes())
    browser.cookies.set(SESSION_COOKIE, cookie)
    workspace = create_planning_workspace(resources, access=BusinessAccess(actor, service.policy))
    body = {"project_ids": [1], "revision": planning_transport.planning_revision_token(workspace.revision()),
            "scope_token": "chart-scope", "nonce": "batch-1"}
    return browser, service, admin, actor, settings, resources, body, assignment


def post_batch(fixture, **changes):
    browser, _, _, _, settings, _, body, _ = fixture
    return browser.post("/api/planning/tasks", json={**body, **changes}, headers={"origin": settings.origin})


def test_http_task_batch_is_scoped_and_never_extends_session_activity(pg_database, task_browser):
    browser, _, _, actor, _, resources, _, _ = task_browser
    with psycopg.connect(pg_database.operator_url) as connection:
        before = connection.execute("SELECT last_activity FROM eppm.app_session WHERE session_hash=%s", (actor.session_hash,)).fetchone()
    response = post_batch(task_browser, project_ids=[1, 1])
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    payload = response.json()
    assert payload["replace_projects"] == [1]
    assert payload["scope_token"] == "chart-scope" and payload["nonce"] == "batch-1"
    assert [row["id"] for row in payload["tasks"]] == ["10"]
    assert payload["tasks"][0]["dependenciesList"] == []
    assert "Hidden" not in response.text
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT last_activity FROM eppm.app_session WHERE session_hash=%s", (actor.session_hash,)).fetchone() == before


@pytest.mark.parametrize("include_other_consumer", [False, True])
def test_task_batches_read_only_assigned_pools_and_keep_other_authorized_consumers(pg_database, task_browser, monkeypatch, include_other_consumer):
    from app.presentation.components.planning_workspace import PlanningWorkspace

    _, service, admin, actor, _, resources, body, _ = task_browser
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Shared',1),(2,'Unrelated',1)")
        connection.execute("""INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,task_id,fte_assigned)
            VALUES(1,1,10,0.6),(1,2,20,0.6),(2,2,20,3)""")
    if include_other_consumer:
        service.grant(admin, actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [2]})
    workspace = create_planning_workspace(resources, access=BusinessAccess(actor, service.policy))
    body["revision"] = planning_transport.planning_revision_token(workspace.revision())
    reads = []
    original = PlanningWorkspace.pool_details

    def bounded_details(self, pool_ids=None):
        assert pool_ids == [1], "Task hydration requested unrelated capacity details"
        reads.append(pool_ids)
        return original(self, pool_ids)

    monkeypatch.setattr(PlanningWorkspace, "pool_details", bounded_details)
    response = post_batch(task_browser)
    assert response.status_code == 200
    assert reads == [[1]]
    task = response.json()["tasks"][0]
    assert task["pools"][0]["pool_capacity"] == 1
    assert task["pools"][0]["is_overassigned"] is include_other_consumer


@pytest.mark.parametrize("empty_project", [False, True])
def test_task_batches_without_assigned_pools_do_not_load_capacity(pg_database, task_browser, monkeypatch, empty_project):
    from app.presentation.components.planning_workspace import PlanningWorkspace

    _, service, _, actor, _, resources, body, _ = task_browser
    if empty_project:
        with psycopg.connect(pg_database.operator_url) as connection:
            connection.execute("DELETE FROM eppm.task_dependencies WHERE task_id=10")
            connection.execute("DELETE FROM eppm.project_task WHERE id=10")
    workspace = create_planning_workspace(resources, access=BusinessAccess(actor, service.policy))
    body["revision"] = planning_transport.planning_revision_token(workspace.revision())

    def unexpected_capacity(*args, **kwargs):
        raise AssertionError("Unassigned tasks must not load any pool capacity")

    monkeypatch.setattr(PlanningWorkspace, "pool_details", unexpected_capacity)
    response = post_batch(task_browser)
    assert response.status_code == 200
    assert len(response.json()["tasks"]) == (0 if empty_project else 1)


def test_dependency_query_work_does_not_grow_with_unrelated_visible_tasks(task_browser, pg_database, monkeypatch):
    """Measure native execution buffers on the actual restricted dependency query."""
    from app.infrastructure.postgresql.planning import PostgresPlanningStore

    _, service, admin, actor, _, resources, _, _ = task_browser
    service.grant(admin, actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [2]})
    workspace = create_planning_workspace(resources, access=BusinessAccess(actor, service.policy))
    plans = []
    original = PostgresPlanningStore._rows

    def measured_rows(self, record_type, query, parameters=()):
        if "WITH selected_tasks" in query:
            plan = self.connection.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, parameters).fetchone()[0][0]["Plan"]
            plans.append(plan)
        return original(self, record_type, query, parameters)

    monkeypatch.setattr(PostgresPlanningStore, "_rows", measured_rows)
    before = workspace.planning.get_dependencies_for_projects([1])
    assert len(before) == 1 and before[0]["predecessor_task_id"] == 20
    assert workspace.planning.get_dependencies_for_projects([1, 1]) == before
    before_plan = plans[-1]
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date)
            SELECT task_id,2,'Unrelated','2026-01-01'::date,'2026-01-05'::date FROM generate_series(100,5099) task_id""")
        connection.execute("""INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id,link_type,lag_days)
            SELECT task_id,20,'FS',0 FROM generate_series(100,5099) task_id""")
        connection.execute("ANALYZE eppm.project_task")
        connection.execute("ANALYZE eppm.task_dependencies")
    assert workspace.planning.get_dependencies_for_projects([1]) == before
    after_plan = plans[-1]
    before_blocks = before_plan["Shared Hit Blocks"] + before_plan["Shared Read Blocks"]
    after_blocks = after_plan["Shared Hit Blocks"] + after_plan["Shared Read Blocks"]
    # Allow index depth and small-table planner changes, not 5,000-row scans.
    def scans(plan):
        selected = {key: plan[key] for key in (
            "Node Type", "Relation Name", "Actual Rows", "Actual Loops", "Rows Removed by Filter", "Shared Hit Blocks"
        ) if key in plan}
        return [selected] + [item for child in plan.get("Plans", []) for item in scans(child)]

    details = "\n".join(str(row) for row in scans(after_plan) if "Relation Name" in row)
    assert after_blocks <= before_blocks + 64, f"{before_blocks} -> {after_blocks}\n{details}"
    for row in scans(after_plan):
        if row.get("Relation Name") in {"project_task", "task_dependencies"}:
            scanned = (row["Actual Rows"] + row.get("Rows Removed by Filter", 0)) * row["Actual Loops"]
            assert scanned <= 2, details


@pytest.mark.parametrize("empty_predecessor", [False, True])
def test_task_batch_reads_one_metadata_snapshot_and_batches_whole_project_bounds(pg_database, task_browser, monkeypatch, empty_predecessor):
    from app.application.services.planning import PlanningService

    _, service, admin, actor, _, resources, body, _ = task_browser
    service.grant(admin, actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [2]})
    with psycopg.connect(pg_database.operator_url) as connection:
        if empty_predecessor:
            connection.execute("DELETE FROM eppm.task_dependencies WHERE predecessor_task_id=20")
            connection.execute("DELETE FROM eppm.project_task WHERE id=20")
        connection.execute("INSERT INTO eppm.task_dependencies(task_id,predecessor_project_id,link_type,lag_days) VALUES(10,2,'FS',2)")
    workspace = create_planning_workspace(resources, access=BusinessAccess(actor, service.policy))
    body["revision"] = planning_transport.planning_revision_token(workspace.revision())
    original = PlanningService.read_task_bundle
    reads = []

    def read_bundle(self, ids):
        reads.append(ids)
        bundle = original(self, ids)
        assert bundle.project_names == {1: "Visible"}
        assert bundle.project_bounds == {"1": ("2026-01-01", "2026-01-05"),
                                         "2": (None, None) if empty_predecessor else ("2026-01-01", "2026-01-05")}
        return bundle

    def redundant_read(*args, **kwargs):
        raise AssertionError("Task HTTP reads must not reload summaries or individual predecessor bounds")

    monkeypatch.setattr(PlanningService, "read_task_bundle", read_bundle)
    monkeypatch.setattr(PlanningService, "get_project_summaries", redundant_read)
    monkeypatch.setattr(PlanningService, "get_project_date_bounds", redundant_read)
    response = post_batch(task_browser)
    assert response.status_code == 200 and reads == [[1]]
    task = response.json()["tasks"][0]
    assert task["project_name"] == "Visible"
    assert len(task["dependenciesList"]) == (1 if empty_predecessor else 2)
    assert bool(task["violations"]) is not empty_predecessor


def test_filtered_chart_still_checks_a_whole_project_predecessor_outside_its_supplied_bounds(pg_database, task_browser):
    from app.presentation.components.planning_data import build_task_payload

    _, service, admin, actor, _, resources, _, _ = task_browser
    service.grant(admin, actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [2]})
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("DELETE FROM eppm.task_dependencies WHERE task_id=10")
        connection.execute("INSERT INTO eppm.task_dependencies(task_id,predecessor_project_id,link_type,lag_days) VALUES(10,2,'FS',2)")
    workspace = create_planning_workspace(resources, access=BusinessAccess(actor, service.policy))
    bounds = {"1": ("2026-01-01", "2026-01-05")}
    tasks = build_task_payload(workspace, [1], bounds, {})
    assert bounds["2"] == ("2026-01-01", "2026-01-05")
    assert len(tasks) == 1 and tasks[0]["project_name"] == "Visible"
    assert tasks[0]["dependenciesList"][0]["is_violated"]
    assert tasks[0]["violations"]


@pytest.mark.parametrize("project_ids", [[2], [1, 2], [999]])
def test_http_rejects_hidden_or_missing_projects_without_partial_data(task_browser, project_ids):
    response = post_batch(task_browser, project_ids=project_ids)
    assert response.status_code == 403
    assert set(response.json()) == {"error"}


@pytest.mark.parametrize("change", ["anonymous", "logout", "disabled", "revoked", "expired"])
def test_http_rechecks_session_and_current_grants_on_every_batch(task_browser, monkeypatch, change):
    browser, service, admin, actor, _, _, _, assignment = task_browser
    assert post_batch(task_browser).status_code == 200
    if change == "anonymous":
        browser.cookies.clear()
    elif change == "logout":
        service.logout(actor)
    elif change == "disabled":
        service.set_status(admin, actor.user_id, "disabled")
    elif change == "revoked":
        service.revoke(admin, assignment)
    else:
        monkeypatch.setattr(service.policy, "clock", lambda: 200000)
    response = post_batch(task_browser)
    assert response.status_code == 403 and "tasks" not in response.json()


@pytest.mark.parametrize("change", ["before", "during", "revoke_during"])
def test_http_does_not_deliver_a_batch_after_data_or_permissions_change(pg_database, task_browser, monkeypatch, change):
    _, service, admin, _, _, resources, _, assignment = task_browser

    def update():
        if change == "revoke_during":
            service.revoke(admin, assignment)
        else:
            with psycopg.connect(pg_database.operator_url) as connection:
                connection.execute("UPDATE eppm.project_task SET progress_pct=50 WHERE id=10")

    if change == "before":
        update()
    else:
        original = planning_transport.build_task_payload

        def read_then_change(*args, **kwargs):
            result = original(*args, **kwargs)
            update()
            return result

        monkeypatch.setattr(planning_transport, "build_task_payload", read_then_change)
    response = post_batch(task_browser)
    assert response.status_code == (403 if change == "revoke_during" else 409)
    assert "tasks" not in response.json()


@pytest.mark.parametrize("field,value", [
    ("project_ids", None), ("project_ids", []), ("project_ids", [1] * 26),
    ("project_ids", [True]), ("project_ids", [1.2]), ("project_ids", [-1]), ("project_ids", [2**63]),
    ("revision", None), ("scope_token", ""), ("nonce", "x" * 129),
])
def test_http_validates_bounded_task_requests(task_browser, field, value):
    assert post_batch(task_browser, **{field: value}).status_code == 400


@pytest.mark.parametrize("content", [b"[1]", b"{", b"\xff", b"x" * 4097])
def test_http_rejects_malformed_or_oversized_bodies(task_browser, content):
    browser, _, _, _, settings, _, _, _ = task_browser
    response = browser.post("/api/planning/tasks", content=content, headers={"origin": settings.origin})
    assert response.status_code == 400


def test_http_rejects_foreign_origins_and_reports_internal_failures_safely(task_browser, monkeypatch):
    browser, _, _, _, _, _, body, _ = task_browser
    assert browser.post("/api/planning/tasks", json=body, headers={"origin": "https://elsewhere.example"}).status_code == 403

    def unavailable(*args, **kwargs):
        raise RuntimeError("internal diagnostic must not be returned")

    monkeypatch.setattr(planning_transport, "build_task_payload", unavailable)
    response = post_batch(task_browser)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "planning_unavailable"
    assert "internal diagnostic" not in response.text


def test_edit_after_http_loading_updates_the_browser_working_set_without_trusting_hidden_ids(business):
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest
    from tests.postgresql.test_planning_ui import planning_app

    resources, _, _, _, manager = business
    with patch("app.presentation.pages.planning._interactive_gantt", return_value=None) as component:
        app = AppTest.from_function(planning_app, args=(resources, manager), default_timeout=30).run()
        assert not app.exception and not app.error
        snapshot = app.session_state["planning_chart_snapshot"]
        assert snapshot["loaded"] == []
        app.session_state["before_event"] = {
            "action": "update_progress", "id": 10, "progress": 40, "nonce": "edit-after-http",
            "scope_token": snapshot["token"], "loaded_project_ids": [1, 2, 999, "1", True],
        }
        app.run()
        assert not app.exception and not app.error
        assert app.session_state["planning_chart_snapshot"]["loaded"] == [1, 2]
        tasks = component.call_args.kwargs["patch"]["tasks"]
        assert next(row for row in tasks if row["id"] == "10")["progress"] == 40
