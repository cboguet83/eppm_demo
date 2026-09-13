"""Portfolio service contracts, bounded enrichment, and cache isolation."""


import pytest
import psycopg
from secrets import token_hex

from app.application.services.business_access import BusinessAccess
from app.infrastructure.postgresql.authorization import configure_signing_key
from app.infrastructure.postgresql.migration import migrate
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture, PostgreSQLFixture
from tests.postgresql.ui import runtime as runtime, access as access

from app.application.services.portfolio import PortfolioService, portfolio_revision_token
from app.infrastructure.postgresql.portfolio import PostgresPortfolioReader
from app.infrastructure.postgresql.seed_projects import create_seed_project
from app.main import create_project_service, create_portfolio_service
from app.presentation.pages.portfolio import _load_portfolio_page


def test_portfolio_enrichment_is_bounded_and_component_input_is_normalized(
    runtime: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    """Enrich only the requested native page, retaining known fixture identities."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        for index in range(105):
            if index < 3:
                connection.execute('UPDATE eppm.project SET name=%s WHERE id=%s', (f'Project {index:03d}', index + 1))
            else:
                create_seed_project(connection, name=f'Project {index:03d}')
    calls = []

    def allocations(project_ids):
        calls.append(project_ids)
        return {project_ids[-1]} if project_ids else set()

    service = PortfolioService(PostgresPortfolioReader(runtime.database, runtime.key, access=access), allocations)
    columns = [{"key": "name", "format": "text"}]
    page = service.get_page(columns, {"filters": [], "sort": {"column": []}, "templates": {}}, "bad")
    assert len(page["rows"]) == len(calls[0]) == 100
    assert calls[0] == list(range(1, 101))
    assert sum(row["is_overallocated"] for row in page["rows"]) == 1
    last = service.get_page(columns, {}, 100)
    assert calls[1] == list(range(101, 106))
    assert last["total"] == 105
    assert service.get_page(columns, {"sort": [], "filters": {"name": "bad"}}, float("inf"))["offset"] == 0
    assert service.get_page(columns, {"search": "missing"})["total"] == 0
    assert calls[-1] == []
    assert service.get_detail(105)["name"] == "Project 104"
    assert service.get_detail(999) is None
    with pytest.raises(ValueError, match="Unknown portfolio column"):
        service.get_facet(columns, {}, 'name";DROP TABLE project;')
    assert service.get_metrics().total_projects == 105

    # Browsing needs schema metadata; manager choices are loaded only by dialogs.
    assert service.get_catalog(include_managers=False).managers == {}

    calls.clear()
    rows = service.get_page(columns, {}, 100, include_allocations=False)["rows"]
    assert [row["project_id"] for row in rows] == list(range(101, 106))
    assert calls == []
    assert all("is_overallocated" not in row for row in rows)
    badges = service.get_allocation_badges([101, 105], portfolio_revision_token(service.revision()))
    assert badges == {"project_ids": [101, 105], "overallocated": [105]}
    assert calls == [[101, 105]]


def test_portfolio_cache_separates_databases_and_refreshes_after_project_writes(
    runtime: RuntimeResources, access: BusinessAccess,
    authorized: AuthorizedFixture, restore_target: PostgreSQLFixture,
) -> None:
    """Matching actor and project IDs cannot share cached rows across databases."""
    columns = [{"key": "name", "format": "text"}]
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='First' WHERE id=1")
    migrate(restore_target.operator_url)
    other = RuntimeResources.from_environment({
        'DATABASE_URL': restore_target.runtime_url, 'DATABASE_CONTEXT_KEY': token_hex(32),
        'DATABASE_POOL_MIN': '1', 'DATABASE_POOL_MAX': '2',
    })
    configure_signing_key(restore_target.operator_url, other.key.hex())
    with psycopg.connect(restore_target.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
        connection.execute("INSERT INTO eppm.project(name) VALUES ('Second')")
        connection.execute("INSERT INTO eppm.app_user(id,status,created_at,updated_at) VALUES (4,'active',900,900)")
        connection.execute("INSERT INTO eppm.app_session VALUES ('session-4',4,950,2000,980,false,false)")
        connection.execute("""INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
            VALUES (4,'business_admin','{"kind":"all"}',900,'test setup')""")
    other.database.open()
    try:
        first = create_portfolio_service(runtime, access=access, include_allocations=False)
        second = create_portfolio_service(other, access=access, include_allocations=False)
        assert first.get_allocation_badges([1], portfolio_revision_token(first.revision())) == {"project_ids": [1], "overallocated": []}
        assert first.revision() != second.revision()
        for service, expected in ((first, "First"), (second, "Second")):
            page = _load_portfolio_page(service.revision(), columns, {}, 0, service)
            assert page['rows'][0]['name'] == expected
        before = first.revision()
        create_project_service(runtime, access=access).update_project(1, "Updated", "Draft", 0, 0, {})
        assert first.revision() != before
        assert _load_portfolio_page(first.revision(), columns, {}, 0, first)['rows'][0]['name'] == 'Updated'
    finally:
        _load_portfolio_page.clear()
        other.database.close()
