"""Bounded global authorization preserves native business gateway semantics."""

from dataclasses import replace

import psycopg
import pytest

from app.application.services.access import AuthorizationPolicy, SessionLimits
from app.domain.access.models import AccessDenied, Permission
from app.infrastructure.postgresql.business import run_business
from app.infrastructure.postgresql.pool import Database
from app.shared.config.database import DatabaseConfig


@pytest.mark.parametrize("user_id,permission,owners,allowed", [
    (4, Permission.EDIT, [1], True),
    (4, Permission.EDIT, [1, 1], True),
    (4, Permission.EDIT, [1, 2, 3], True),
    (4, Permission.EDIT, [], False),
    (4, Permission.EDIT, [999], False),
    (4, Permission.EDIT, [1, 999], False),
    (4, Permission.EDIT, [None], False),
    (4, Permission.EDIT, [0], False),
    (4, Permission.EDIT, [2**63], False),
    (4, Permission.CREATE, None, True),
    (1, Permission.READ, [1, 2], True),
    (1, Permission.EDIT, [1], True),
    (1, Permission.EDIT, [2], False),
    (1, Permission.READ, [3], False),
    (2, Permission.READ, [3], True),
    (2, Permission.EDIT, [3], False),
    (3, None, None, False),
    (5, Permission.ACCESS, None, False),
])
def test_global_and_scoped_permissions_require_every_existing_owner(
    authorized, user_id, permission, owners, allowed,
):
    calls = []

    def operation(connection):
        calls.append(True)
        return connection.execute("SELECT id FROM eppm.project ORDER BY id").fetchall()

    def run():
        return run_business(authorized.database, authorized.key, authorized.binding(user_id).access,
                            operation, write=True, permission=permission, project_ids=owners)

    if allowed:
        assert run()
        assert calls == [True]
    else:
        with pytest.raises(AccessDenied):
            run()
        assert calls == []


def test_global_reader_can_browse_an_empty_portfolio_without_admitting_ungranted_accounts(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("DELETE FROM eppm.project")

    for user_id in (1, 3, 4, 5):
        def run():
            return run_business(authorized.database, authorized.key, authorized.binding(user_id).access,
                                lambda connection: connection.execute("SELECT id FROM eppm.project").fetchall())
        if user_id == 4:
            assert run() == []
        else:
            with pytest.raises(AccessDenied):
                run()


def test_global_permission_shortcut_rechecks_required_administrator_mfa(authorized):
    access = replace(authorized.binding(4).access, policy=AuthorizationPolicy(
        lambda: 1000, SessionLimits(require_admin_mfa=True)))

    def run():
        return run_business(authorized.database, authorized.key, access,
                            lambda connection: connection.execute("SELECT id FROM eppm.project WHERE id=1").fetchone(),
                            write=True, permission=Permission.EDIT, project_ids=[1])

    with pytest.raises(AccessDenied):
        run()
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.app_session SET mfa=true WHERE user_id=4")
    assert run() == (1,)


@pytest.mark.parametrize("fails", [False, True])
def test_point_write_planner_preference_does_not_leak_after_commit_or_rollback(authorized, fails):
    database = Database(DatabaseConfig(authorized.setup.runtime_url, pool_min=1, pool_max=1))
    def operation(connection):
        assert connection.execute("SHOW enable_seqscan").fetchone() == ("off",)
        if fails:
            raise ValueError("Rejected test input")

    def run():
        return run_business(database, authorized.key, authorized.binding(4).access,
                            operation, write=True, permission=Permission.EDIT, project_ids=[1])

    database.open()
    try:
        if fails:
            with pytest.raises(ValueError, match="Rejected test input"):
                run()
        else:
            run()
        assert run_business(database, authorized.key, authorized.binding(1).access,
                            lambda connection: connection.execute("SHOW enable_seqscan").fetchone()) == ("on",)
    finally:
        database.close()
