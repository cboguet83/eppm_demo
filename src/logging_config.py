"""Compatibility exports for logging moved to app.shared.logging."""

from app.shared.logging import get_logger, setup_logging

__all__ = ["get_logger", "setup_logging"]
