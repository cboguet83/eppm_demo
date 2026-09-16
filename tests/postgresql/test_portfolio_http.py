"""Deferred portfolio warnings retain current session, project, and revision checks."""


import psycopg
import pytest

from app.application.services.business_access import BusinessAccess
from app.application.services.portfolio import portfolio_revision_token
from app.domain.access.models import Permission
from app.infrastructure.authentication.planning import PlanningReadRoutes
from app.main import create_portfolio_service
from tests.postgresql.test_planning_http import task_browser as task_browser
from tests.postgresql.test_session_transport import transport as transport


@pytest.fixture
def badge_browser(pg_database, task_browser):
    browser, service, _, actor, _, resources, body, _ = task_browser
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES (1,'Shared pool',1)")
        connection.execute("INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date,project_plan_id) VALUES (1,1,2,'2026-01-01','2026-01-05',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(1,2,3,'2026-01-01','2026-01-05',(SELECT id FROM eppm.project_plan WHERE project_id=2 AND is_current))")

    def read_allocations(current_actor, ids, revision):
        access = BusinessAccess(current_actor, service.policy)
        service.gateway.run(lambda store: access.require(store, Permission.READ, ids), actor=current_actor)
        return create_portfolio_service(resources, access=access).get_allocation_badges(ids, revision)

    browser.app.router.routes.extend(PlanningReadRoutes(service, read_allocations, read_allocations=read_allocations).routes())
    portfolio = create_portfolio_service(resources, access=BusinessAccess(actor, service.policy))
    body["revision"] = portfolio_revision_token(portfolio.revision())
    return task_browser


def post_badges(fixture, **changes):
    browser, _, _, _, settings, _, body, _ = fixture
    return browser.post("/api/portfolio/allocations", json={**body, **changes}, headers={"origin": settings.origin})


def test_badges_are_scoped_and_do_not_extend_session_activity(pg_database, badge_browser):
    _, _, _, actor, _, resources, _, _ = badge_browser
    with psycopg.connect(pg_database.operator_url) as connection:
        before = connection.execute("SELECT last_activity FROM eppm.app_session WHERE session_hash=%s", (actor.session_hash,)).fetchone()
    response = post_badges(badge_browser, project_ids=[1, 1])
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json() == {"project_ids": [1], "overallocated": [1], "scope_token": "chart-scope", "nonce": "batch-1"}
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("SELECT last_activity FROM eppm.app_session WHERE session_hash=%s", (actor.session_hash,)).fetchone() == before


@pytest.mark.parametrize("ids", [[2], [1, 2], [999]])
def test_badges_reject_hidden_or_missing_projects_without_partial_results(badge_browser, ids):
    response = post_badges(badge_browser, project_ids=ids)
    assert response.status_code == 403
    assert set(response.json()) == {"error"}


@pytest.mark.parametrize("change", ["anonymous", "logout", "disabled", "revoked", "expired"])
def test_badges_recheck_current_session_and_grants(badge_browser, monkeypatch, change):
    browser, service, admin, actor, _, _, _, assignment = badge_browser
    assert post_badges(badge_browser).status_code == 200
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
    assert post_badges(badge_browser).status_code == 403


@pytest.mark.parametrize("change", ["before", "during", "revoke_during"])
def test_badges_reject_allocation_or_scope_changes_during_calculation(pg_database, badge_browser, monkeypatch, change):
    from app.application.services.project_overallocation import ProjectOverallocationService

    _, service, admin, _, _, resources, _, assignment = badge_browser

    def update():
        if change == "revoke_during":
            service.revoke(admin, assignment)
        else:
            with psycopg.connect(pg_database.operator_url) as connection:
                connection.execute("UPDATE eppm.resource_pool_assignment SET fte_assigned=0 WHERE project_id=1")

    if change == "before":
        update()
    else:
        original = ProjectOverallocationService.overallocated_project_ids

        def read_then_change(self, ids):
            result = original(self, ids)
            update()
            return result

        monkeypatch.setattr(ProjectOverallocationService, "overallocated_project_ids", read_then_change)
    response = post_badges(badge_browser)
    assert response.status_code == (403 if change == "revoke_during" else 409)
    assert set(response.json()) == {"error"}


@pytest.mark.parametrize("field,value", [
    ("project_ids", []), ("project_ids", [1] * 26), ("project_ids", [True]),
    ("project_ids", [1.2]), ("project_ids", [-1]), ("project_ids", [2**63]),
    ("revision", None), ("scope_token", ""), ("nonce", "x" * 129),
])
def test_badge_requests_are_bounded_and_validated(badge_browser, field, value):
    assert post_badges(badge_browser, **{field: value}).status_code == 400


@pytest.mark.parametrize("content", [b"[1]", b"{", b"\xff", b"x" * 4097])
def test_badge_requests_reject_malformed_or_oversized_bodies(badge_browser, content):
    browser, _, _, _, settings, _, _, _ = badge_browser
    assert browser.post("/api/portfolio/allocations", content=content, headers={"origin": settings.origin}).status_code == 400


def test_badges_reject_foreign_origins_and_handle_errors_safely(badge_browser, monkeypatch):
    from app.application.services.portfolio import PortfolioService

    browser, _, _, _, _, _, body, _ = badge_browser
    assert browser.post("/api/portfolio/allocations", json=body, headers={"origin": "https://elsewhere.example"}).status_code == 403

    def unavailable(*args, **kwargs):
        raise RuntimeError("internal diagnostic must remain private")

    monkeypatch.setattr(PortfolioService, "get_allocation_badges", unavailable)
    response = post_badges(badge_browser)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "portfolio_unavailable"
    assert "internal diagnostic" not in response.text
