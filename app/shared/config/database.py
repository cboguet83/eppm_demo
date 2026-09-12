"""Validated PostgreSQL settings, with credentials excluded from representations."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from urllib.parse import urlsplit


def validate_database_url(value: str) -> None:
    """Require an explicit PostgreSQL URL without exposing invalid input.

    Args:
        value: Deployment-supplied database URL, potentially containing secrets.

    Raises:
        ValueError: If the URL is missing required connection coordinates.
    """
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"postgresql", "postgres"}
            and parsed.hostname and parsed.username
            and parsed.path not in {"", "/"} and not parsed.fragment
            and (parsed.port is None or parsed.port > 0)
            and not any(character.isspace() for character in value)
            and "\\" not in value
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError("Configure a valid PostgreSQL database URL.")


@dataclass(frozen=True)
class DatabaseConfig:
    """One process pool's connection limits and bounded request timeouts."""

    url: str = field(repr=False)
    pool_min: int = 2
    pool_max: int = 20
    acquire_timeout: float = 5.0
    statement_timeout: float = 10.0

    def __post_init__(self) -> None:
        validate_database_url(self.url)
        if (type(self.pool_min) is not int or type(self.pool_max) is not int
                or not 1 <= self.pool_min <= self.pool_max <= 200):
            raise ValueError("Database pool sizes must satisfy 1 <= minimum <= maximum <= 200.")
        for value in (self.acquire_timeout, self.statement_timeout):
            if (type(value) not in {int, float} or not math.isfinite(value)
                    or not 0.001 <= value <= 300):
                raise ValueError("Database timeouts must be between 0.001 and 300 seconds.")

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> DatabaseConfig:
        """Load runtime credentials only; operator credentials are never a fallback."""
        try:
            return cls(
                url=environment.get("DATABASE_URL", ""),
                pool_min=int(environment.get("DATABASE_POOL_MIN", "2")),
                pool_max=int(environment.get("DATABASE_POOL_MAX", "20")),
                acquire_timeout=float(environment.get("DATABASE_ACQUIRE_TIMEOUT", "5")),
                statement_timeout=float(environment.get("DATABASE_STATEMENT_TIMEOUT", "10")),
            )
        except (ValueError, TypeError):
            raise ValueError("Invalid PostgreSQL runtime configuration.") from None
