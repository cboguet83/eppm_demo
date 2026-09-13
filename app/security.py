"""Composition of trusted authentication services at the application boundary."""

from __future__ import annotations

from secrets import token_urlsafe
from time import time
from typing import TYPE_CHECKING

from app.application.services.access import AccessService, AuthorizationPolicy, SessionLimits
from app.infrastructure.postgresql.access import PostgresAccessGateway
from app.shared.config.authentication import AuthenticationConfig

if TYPE_CHECKING:
    from app.runtime import RuntimeResources


def create_access_service(resources: RuntimeResources, settings: AuthenticationConfig) -> AccessService:
    """Construct request-independent services with explicit clock and session policy."""
    limits = SessionLimits(settings.idle_seconds, settings.reauthentication_seconds,
                           settings.environment != "development")
    policy = AuthorizationPolicy(lambda: int(time()), limits)
    return AccessService(PostgresAccessGateway(resources.database, resources.key, policy),
                         policy, settings.issuer, lambda: token_urlsafe(32))
