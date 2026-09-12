"""Complete actor-bound business callbacks with native row-level enforcement."""

from collections.abc import Callable, Collection
import json

import psycopg

from app.application.services.business_access import BusinessAccess
from app.domain.access.models import AccessDenied, Actor, Permission
from app.infrastructure.postgresql.access import PostgresAccessStore
from app.infrastructure.postgresql.authorization import ActorBinding, ServerRequestSigner
from app.infrastructure.postgresql.pool import Database
from app.shared.logging import get_logger

logger = get_logger(__name__)


def run_business[Result](database: Database, key: bytes, access: BusinessAccess,
                         operation: Callable[[psycopg.Connection], Result], *, write: bool = False,
                         permission: Permission | None = None,
                         project_ids: Collection[int] | None = None) -> Result:
    """Authorize and replay the entire business operation in one native snapshot.

    Args:
        database: Shared restricted runtime pool; never operator credentials.
        key: Explicit server key for trusted request binding.
        access: Actor and current policy supplied by application composition.
        operation: Complete database work without external effects or UI rendering.
        write: Request a serializable writer instead of a repeatable-read snapshot.
        permission: Optional additional use-case permission checked on every retry.
        project_ids: Concrete project scope for that additional permission.
    """
    project_ids = tuple(project_ids) if project_ids is not None else None
    try:
        if not isinstance(access.actor, Actor):
            raise AccessDenied()
        signer, binding = ServerRequestSigner(key), ActorBinding(access, key)

        def callback(connection: psycopg.Connection) -> Result:
            security = PostgresAccessStore(connection, signer, access.policy, access.actor, writable=write)
            if permission is not None:
                access.require(security, permission, project_ids)
            access.projects(security)
            return operation(connection)

        try:
            return database.run(callback, write=write, bind=binding)
        except psycopg.errors.InsufficientPrivilege:
            raise AccessDenied() from None
    except AccessDenied:
        logger.warning("security.event %s", json.dumps({
            "action": "business.authorization_denied", "outcome": "denied",
            "actor": access.audit_actor, "correlation": access.actor.correlation_id,
            "permission": permission.value if permission is not None else "scoped_operation",
        }))
        raise
