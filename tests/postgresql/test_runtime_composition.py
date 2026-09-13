"""Real PostgreSQL application composition, scoped navigation and shared resources."""

from concurrent.futures import ThreadPoolExecutor
from secrets import token_hex

import psycopg
import pytest

from app import main
from app.domain.access.models import AccessDenied, DeploymentActor
from app.application.services.business_access import BusinessAccess
from app.presentation.navigation import (
    PAGE_ACCESS, PAGE_BUDGET, PAGE_DASHBOARD, PAGE_FINANCE, PAGE_PLANNING,
    PAGE_PORTFOLIO, PAGE_SCHEMA_DEF, PAGE_SETTINGS,
)
from app.runtime import RuntimeResources


@pytest.mark.parametrize('user_id,expected', [
    (1, {PAGE_DASHBOARD, PAGE_FINANCE, PAGE_PORTFOLIO, PAGE_PLANNING, PAGE_BUDGET}),
    (2, {PAGE_DASHBOARD, PAGE_FINANCE, PAGE_PORTFOLIO, PAGE_PLANNING, PAGE_BUDGET}),
    (3, {PAGE_DASHBOARD, PAGE_FINANCE}),
    (4, {PAGE_DASHBOARD, PAGE_FINANCE, PAGE_PORTFOLIO, PAGE_PLANNING, PAGE_BUDGET, PAGE_SCHEMA_DEF, PAGE_SETTINGS}),
    (5, {PAGE_DASHBOARD, PAGE_FINANCE}),
])
def test_workspace_visibility_uses_the_native_actor_and_preserves_empty_account_views(authorized, user_id, expected):
    runtime = RuntimeResources(authorized.database, authorized.key)
    workspace = main.create_application_workspace(runtime, access=authorized.binding(user_id).access)
    assert set(workspace.pages) == expected
    assert workspace.database_identity == runtime.identity
    if workspace.totals is not None:
        assert workspace.totals()['tasks'] == 0


def test_access_management_requires_a_real_authentication_service_and_current_session(authorized):
    from app.application.services.access import AccessService
    from app.infrastructure.postgresql.access import PostgresAccessGateway

    runtime = RuntimeResources(authorized.database, authorized.key)
    access = authorized.binding(5).access
    authentication = AccessService(PostgresAccessGateway(runtime.database, runtime.key, access.policy),
                                   access.policy, 'https://issuer.example.test', lambda: 'unused')
    workspace = main.create_application_workspace(runtime, access=access, authentication=authentication)
    assert set(workspace.pages) == {PAGE_DASHBOARD, PAGE_FINANCE, PAGE_ACCESS}
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.app_session SET revoked=true WHERE session_hash='session-5'")
    with pytest.raises(AccessDenied):
        main.create_application_workspace(runtime, access=access, authentication=authentication)


def test_composition_does_not_offer_operator_business_access(authorized):
    runtime = RuntimeResources(authorized.database, authorized.key)
    access = BusinessAccess(DeploymentActor('operator', 'request'), authorized.binding().access.policy)
    with pytest.raises(AccessDenied):
        main.create_application_workspace(runtime, access=access)


def test_planning_and_capacity_instances_share_the_injected_cache_and_keep_actor_scopes(authorized):
    runtime = RuntimeResources(authorized.database, authorized.key)
    first = main.create_planning_service(runtime, access=authorized.binding(1).access)
    second = main.create_planning_service(runtime, access=authorized.binding(2).access)
    capacity = main.create_pool_capacity_cache(runtime, access=authorized.binding(1).access)
    assert first._gateway.cache.state is second._gateway.cache.state is capacity.cache.state is runtime.caches
    assert first._gateway.database is second._gateway.database is capacity.cache.database is runtime.database
    reader = main.create_portfolio_service(runtime, access=authorized.binding(1).access, include_allocations=False)
    assert reader.get_metrics().total_projects == 2
    assert main.create_portfolio_service(runtime, access=authorized.binding(2).access).get_metrics().total_projects == 1


def test_process_provider_constructs_one_closed_resource_under_concurrent_first_calls(pg_database, monkeypatch):
    import app.runtime as module

    monkeypatch.setenv('DATABASE_URL', pg_database.runtime_url)
    monkeypatch.setenv('DATABASE_CONTEXT_KEY', token_hex(32))
    # The only reset here is a closed test provider, not Streamlit's user cache.
    module._configured_runtime.cache_clear()
    try:
        with ThreadPoolExecutor(max_workers=16) as workers:
            resources = list(workers.map(lambda _: module.process_runtime(), range(64)))
        assert all(resource is resources[0] for resource in resources)
        assert resources[0].database.statistics().get('connections_num', 0) == 0
        assert resources[0].caches is module.process_runtime().caches
    finally:
        module._configured_runtime.cache_clear()
