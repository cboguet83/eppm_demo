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
        db_path: Path to the SQLite database file.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        app_env: Environment mode ('development', 'staging', 'production').
    """

    db_path: str = os.getenv("DB_NAME", "ppm_mock.db")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    app_env: str = os.getenv("APP_ENV", "development")


config = AppConfig()
