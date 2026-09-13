"""Native lease ownership and committed display revision regressions."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import psycopg
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool
import pytest

from app.application.exceptions import PlanningConflictError
from app.application.services.business_access import BusinessAccess
from app.infrastructure.postgresql.revisions import snapshot
from app.main import create_planning_service
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access


@pytest.mark.parametrize("operation", ["read", "write", "rollback"])
def test_task_repository_finishes_transactions_before_returning_every_lease(
    runtime: RuntimeResources, access: BusinessAccess, operation: str,
) -> None:
    """Observe the real lease before pool return, including failed dependency saves."""
    planning = create_planning_service(runtime, access=access)
    first = planning.create_milestone(1, "First", "Build", "2026-01-01", "2026-01-05", 0)
    predecessor = planning.create_milestone(2, "Source", "Build", "2026-01-01", "2026-01-02", 0)
    planning.save_task_dependencies(first, [{"predecessor_task_id": predecessor}])
    acquire = ConnectionPool.connection
    released_states: list[TransactionStatus] = []

    @contextmanager
    def observed_lease(pool: ConnectionPool, timeout: float | None = None) -> Iterator[psycopg.Connection]:
        with acquire(pool, timeout=timeout) as connection:
            try:
                yield connection
            finally:
                released_states.append(connection.info.transaction_status)

    with patch.object(ConnectionPool, "connection", observed_lease):
        if operation == "read":
            assert len(planning.get_all_milestones()) == 2
        elif operation == "write":
            assert planning.update_dates(first, "2026-02-01", "2026-02-02")
        else:
            with pytest.raises(PlanningConflictError):
                planning.save_task_dependencies(first, [{"predecessor_task_id": 999}])

    assert released_states and all(state == TransactionStatus.IDLE for state in released_states)
    # A new real operation works after every exit, with committed or rolled-back data.
    assert [link["predecessor_task_id"] for link in planning.get_task_dependencies(first)] == [predecessor]
    task = planning.get_milestone_by_id(first)
    expected = ("2026-02-01", "2026-02-02") if operation == "write" else ("2026-01-01", "2026-01-05")
    assert (task["start_date"], task["end_date"]) == expected


def test_revision_tracks_equal_length_commits_and_return_to_original_values(
    runtime: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    """Revisions depend on committed source changes, including value round trips."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='first' WHERE id=1")

    def revision() -> str:
        return snapshot(runtime.database, runtime.key, access).token()

    before = revision()
    assert revision() == before
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='other' WHERE id=1")
        assert revision() == before
    after = revision()
    assert after != before and revision() == after

    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='third' WHERE id=1")
        connection.rollback()
    assert revision() == after

    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project SET name='first' WHERE id=1")
    assert revision() not in {before, after}
