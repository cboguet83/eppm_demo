"""Layered application package with lazy exports for former app.py callers.

Importing domain or application modules never initializes Streamlit or storage.
The compatibility exports are retired as their external callers migrate.
"""

from importlib import import_module

__all__ = [
    "parse_cli_args", "run_app", "bootstrap_database", "load_full_schema",
    "generate_param_id", "get_next_available_group_order",
    "calculate_portfolio_metrics", "flatten_dynamic_attributes", "DB_NAME",
]


def __getattr__(name: str) -> object:
    """Resolve documented legacy entry-point helpers only when requested."""
    if name in __all__ or name in {"_get_database_seed_counts", "_get_planning_totals"}:
        owner = "app.main" if name in {"parse_cli_args", "run_app"} else "app.compatibility"
        return getattr(import_module(owner), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
