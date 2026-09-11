"""Composition of trusted authentication services at the application boundary."""

from secrets import token_urlsafe
from time import time

from app.application.services.access import AccessService, AuthorizationPolicy, SessionLimits
from app.infrastructure.repositories.access import SqliteAccessGateway
from app.shared.config.authentication import AuthenticationConfig


def create_access_service(db_path: str, settings: AuthenticationConfig) -> AccessService:
    """Construct request-independent services with explicit clock and session policy."""
    limits = SessionLimits(settings.idle_seconds, settings.reauthentication_seconds,
                           settings.environment != "development")
    return AccessService(SqliteAccessGateway(db_path), AuthorizationPolicy(lambda: int(time()), limits),
                         settings.issuer, lambda: token_urlsafe(32))
