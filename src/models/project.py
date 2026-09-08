"""Compatibility exports for project records and portfolio summaries."""

from app.domain.projects.project import Project
from app.application.ports.portfolio import PortfolioMetrics

__all__ = ["Project", "PortfolioMetrics"]
