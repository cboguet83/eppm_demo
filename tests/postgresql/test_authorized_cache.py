"""Native portfolio cache keys retain scope and data/activity distinctions."""

import psycopg

from app.infrastructure.postgresql.portfolio import PostgresPortfolioReader
from app.presentation.components.authorized_cache import authorized_cache
from tests.postgresql.business import business


def test_compact_cache_reuses_stable_scope_and_isolates_users(business):
    path, service, _, editor, manager = business
    reader = PostgresPortfolioReader(path.database, path.key, access=editor)
    admin_reader = PostgresPortfolioReader(path.database, path.key, access=manager)
    calculations = []

    @authorized_cache(show_spinner=False)
    def load(revision, _service):
        calculations.append(revision)
        return _service.get_page([], {})["total"]

    assert load((), reader) == 1
    service.activity(editor.actor)
    assert load((), reader) == 1
    assert load((), admin_reader) == 2
    assert load((), reader) == 1
    assert len(calculations) == 2
    assert calculations[0] == ((), reader.revision())
    load.clear()


def test_compact_cache_refreshes_after_scope_and_business_changes(business, pg_database):
    path, service, admin, editor, _ = business
    reader = PostgresPortfolioReader(path.database, path.key, access=editor)
    calculations = []

    @authorized_cache(show_spinner=False)
    def load(revision, _service):
        calculations.append(revision)
        return [row["name"] for row in _service.get_page([], {})["rows"]]

    assert load((), reader) == ["Visible"]
    service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [2]})
    assert load((), reader) == ["Visible", "Hidden"]
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='Updated' WHERE id=1")
    assert load((), reader) == ["Updated", "Hidden"]
    assert load((), reader) == ["Updated", "Hidden"]
    assert len(calculations) == 3
    load.clear()
