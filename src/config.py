"""Compatibility exports for settings moved to app.shared.config."""

from app.shared.config import AppConfig, config

__all__ = ["AppConfig", "config"]
