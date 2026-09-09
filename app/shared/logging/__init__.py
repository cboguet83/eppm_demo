"""Logging configuration module for PPM Studio Pro.

Configures structured console logging with timestamping, module names, and
configurable log levels.
"""

import logging
import sys
from typing import TextIO

from app.shared.config import config


def setup_logging(*, stream: TextIO | None = None) -> None:
    """Configures the root logger based on application configuration."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout if stream is None else stream)],
        force=True,
    )
    # OAuth client debug output includes PKCE verifiers; HTTP access logs include
    # authorization codes in callback query strings. Emit our safe security events.
    for name in ("authlib", "httpx", "httpx2", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> logging.Logger:
    """Returns a configured logger instance for a given module name.

    Args:
        name: Name of the module or component.

    Returns:
        logging.Logger: Configured logger instance.
    """
    return logging.getLogger(name)
