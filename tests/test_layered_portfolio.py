"""Portfolio service contracts, bounded enrichment, and cache isolation."""

from app.operator_services import deployment_access
from contextlib import closing
from pathlib import Path

import pytest

from app.application.services.portfolio import PortfolioService, portfolio_revision_token
from app.infrastructure.database.connection import get_db
from app.infrastructure.repositories.portfolio import SqlitePortfolioReader
from app.infrastructure.database.seed_projects import create_seed_project
from app.operator_services import create_project_service, create_portfolio_service
from app.presentation.pages.portfolio import _load_portfolio_page
from app.infrastructure.database.schema_init import init_db


def test_portfolio_enrichment_is_bounded_and_component_input_is_normalized(tmp_path: Path) -> None:
    path = str(tmp_path / "portfolio.db")
    init_db(path)
    with closing(get_db(path)) as conn, conn:
        for index in range(105):
            create_seed_project(conn, name=f"Project {index:03d}")
    calls = []

    def allocations(project_ids):
        calls.append(project_ids)
        return {project_ids[-1]} if project_ids else set()

    service = PortfolioService(SqlitePortfolioReader(path, access=deployment_access()), allocations)
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


def test_portfolio_cache_separates_databases_and_refreshes_after_project_writes(tmp_path: Path) -> None:
    columns = [{"key": "name", "format": "text"}]
    services = []
    for name in ("First", "Second"):
        path = str(tmp_path / f"{name}.db")
        init_db(path)
        create_project_service(path).create_project(name=name)
        services.append(create_portfolio_service(path, include_allocations=False))
    first, second = services
    assert first.get_allocation_badges([1], portfolio_revision_token(first.revision())) == {"project_ids": [1], "overallocated": []}
    assert first.revision() != second.revision()
    for service, expected in ((first, "First"), (second, "Second")):
        page = _load_portfolio_page(service.revision(), columns, {}, 0, service)
        assert page["rows"][0]["name"] == expected
    before = first.revision()
    create_project_service(str(tmp_path / "First.db")).update_project(1, "Updated", "Draft", 0, 0, {})
    assert first.revision() != before
    assert _load_portfolio_page(first.revision(), columns, {}, 0, first)["rows"][0]["name"] == "Updated"
    _load_portfolio_page.clear()
