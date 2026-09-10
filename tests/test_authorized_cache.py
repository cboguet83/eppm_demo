"""Compact revision hashing preserves authorization and display invalidation."""

from contextlib import closing

import pytest

from app.infrastructure.database.connection import get_db
from app.infrastructure.repositories.portfolio import SqlitePortfolioReader
from app.presentation.components.authorized_cache import authorized_cache
from tests.test_business_transaction_security import business as business


def test_compact_cache_reuses_stable_scope_and_isolates_users(business):
    path, service, _, editor, manager = business
    reader = SqlitePortfolioReader(path, access=editor)
    admin_reader = SqlitePortfolioReader(path, access=manager)
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


def test_compact_cache_refreshes_after_scope_and_business_changes(business):
    path, service, admin, editor, _ = business
    reader = SqlitePortfolioReader(path, access=editor)
    calculations = []

    @authorized_cache(show_spinner=False)
    def load(revision, _service):
        calculations.append(revision)
        return [row["name"] for row in _service.get_page([], {})["rows"]]

    assert load((), reader) == ["Visible"]
    service.grant(admin, editor.actor.user_id, "project_viewer", {"kind": "projects", "project_ids": [2]})
    assert load((), reader) == ["Visible", "Hidden"]
    with closing(get_db(path)) as connection, connection:
        connection.execute("UPDATE project SET name='Updated' WHERE id=1")
    assert load((), reader) == ["Updated", "Hidden"]
    assert load((), reader) == ["Updated", "Hidden"]
    assert len(calculations) == 3
    load.clear()


def test_compact_cache_preserves_other_hash_functions_and_arguments():
    class Reference:
        def __init__(self, value):
            self.value = value

    class Owner:
        calls = 0

        def revision(self):
            self.calls += 1
            return ("database", 1, ("actor", "session"), tuple(range(5000)))

    owner = Owner()
    calculations = []
    hashes = {Reference: lambda reference: reference.value, tuple: repr}

    @authorized_cache(show_spinner=False, hash_funcs=hashes)
    def load(revision, reference, template, locale, project_ids, *, _workspace):
        calculations.append(revision)
        return template, locale, project_ids, reference.value

    args = ((), Reference("one"), 1, "en", (1, 2))
    first = load(*args, _workspace=owner)
    assert load(*args, _workspace=owner) == first
    assert load((), Reference("two"), 1, "en", (1, 2), _workspace=owner) != first
    assert load((), Reference("one"), 2, "en", (1, 2), _workspace=owner) != first
    assert load((), Reference("one"), 1, "fr", (1, 2), _workspace=owner) != first
    assert load((), Reference("one"), 1, "en", (2,), _workspace=owner) != first
    assert load(("changed",), *args[1:], _workspace=owner) == first
    assert len(calculations) == 6
    assert owner.calls == 7
    assert len(hashes) == 2
    load.clear()
    assert load(*args, _workspace=owner) == first
    assert len(calculations) == 7


def test_protected_cache_requires_a_current_revision_owner():
    @authorized_cache(show_spinner=False)
    def load(revision):
        return "unreachable"

    with pytest.raises(ValueError, match="revision owner"):
        load(())


@pytest.mark.parametrize("index,value", [
    (0, "another.db"), (1, "another-epoch"), (2, 8), (3, 4),
    (4, ("user", "another-session")), (4, ("another-user", "session")),
    (5, tuple(range(9999)) + (10001,)),
])
def test_complete_revision_prevents_cross_source_or_changed_scope_cache_hits(index, value):
    class Owner:
        value = ("source.db", "epoch", 7, 3, ("user", "session"), tuple(range(10000)))

        def revision(self):
            return self.value

    owner = Owner()
    calculations = []

    @authorized_cache(show_spinner=False)
    def load(revision, *, _service):
        calculations.append(1)
        return len(calculations)

    assert load((), _service=owner) == 1
    assert load((), _service=owner) == 1
    owner.value = owner.value[:index] + (value,) + owner.value[index + 1:]
    assert load((), _service=owner) == 2
    assert load((), _service=owner) == 2
    load.clear()
