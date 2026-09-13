"""Configuration module for PPM Studio Pro.

Follows 12-factor application design by reading settings from environment
variables with safe, sensible defaults.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    """Immutable application configuration settings.

    Attributes:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        app_env: Environment mode ('development', 'staging', 'production').
        force_reseed: Whether to force database re-seeding on application startup.
        seed_projects_count: Number of projects to generate when force-reseeding (0 uses default seed).
    """

    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    app_env: str = os.getenv("APP_ENV", "development")
    force_reseed: bool = os.getenv("FORCE_RESEED", "false").lower() in ("true", "1", "yes")
    seed_projects_count: int = int(os.getenv("SEED_PROJECTS_COUNT", "0"))


config = AppConfig()
