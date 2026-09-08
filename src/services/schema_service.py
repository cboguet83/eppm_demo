"""Compatibility helpers delegating schema identifiers and validation to the core."""

from typing import Any

import pandas as pd

from app.main import create_schema_service
from app.domain.projects.schema import missing_required_properties
from src.repositories.schema_errors import legacy_schema_errors


class SchemaService:
    """Preserve static helper signatures used by the legacy shell and integrations."""

    @staticmethod
    def get_next_available_group_order(db_path: str | None = None) -> int:
        """Read the next group-order preview through the schema application service."""
        with legacy_schema_errors():
            return create_schema_service(db_path).get_next_available_group_order()

    @staticmethod
    def generate_param_id(db_path: str | None = None) -> str:
        """Retain the historical property-ID preview, including legacy schemas."""
        with legacy_schema_errors():
            return create_schema_service(db_path).generate_param_id()

    @staticmethod
    def validate_project_dynamic_attributes(
        dynamic_attributes: dict[str, Any], params_df: pd.DataFrame,
    ) -> list[str]:
        """Adapt flexible legacy frames to pure required-value validation."""
        if params_df.empty or "mandatory" not in params_df.columns:
            return []
        records = params_df.astype(object).where(pd.notna(params_df), None).to_dict("records")
        return missing_required_properties(dynamic_attributes, records)
