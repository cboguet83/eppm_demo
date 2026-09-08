"""Logging configuration module for PPM Studio Pro.

Configures structured console logging with timestamping, module names, and
configurable log levels.
"""

import logging
import sys

from app.shared.config import config


def setup_logging() -> None:
    """Configures the root logger based on application configuration."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """Returns a configured logger instance for a given module name.

    Args:
        name: Name of the module or component.

    Returns:
        logging.Logger: Configured logger instance.
    """
    return logging.getLogger(name)
