"""Compatibility exports for portfolio display and decimal metrics helpers."""

from app.presentation.components.budget_frames import calculate_frame_metrics
from app.presentation.components.planning_catalog import flatten_dynamic_attributes


class PortfolioService:
    """Keep the historical static helpers as delegates to their migrated owners."""

    calculate_portfolio_metrics = staticmethod(calculate_frame_metrics)
    flatten_dynamic_attributes = staticmethod(flatten_dynamic_attributes)
