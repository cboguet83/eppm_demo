"""DataFrame formatting for typed schema records at the presentation boundary."""

from dataclasses import asdict

import pandas as pd

from app.domain.projects.schema import SchemaGroup, SchemaParameter, SchemaParamOption


def groups_frame(groups: list[SchemaGroup]) -> pd.DataFrame:
    """Retain columns even when the schema has no groups."""
    return pd.DataFrame([asdict(group) for group in groups], columns=["id", "group_name", "display_order"])


def parameters_frame(parameters: list[SchemaParameter]) -> pd.DataFrame:
    """Format property records with stable IDs and nullable group references."""
    return pd.DataFrame([asdict(parameter) for parameter in parameters], columns=[
        "param_id", "group_id", "param_name", "param_type", "mandatory", "alias", "applies_to_all",
    ])


def options_frame(options: list[SchemaParamOption]) -> pd.DataFrame:
    """Format configured choices in their supplied display order."""
    return pd.DataFrame([asdict(option) for option in options], columns=["id", "param_id", "option_value", "display_order"])
