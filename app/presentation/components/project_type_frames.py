"""Adapt application results to dataframes used by existing Streamlit screens."""

from dataclasses import asdict

import pandas as pd

from app.domain.projects.project_types import ProjectType, TemplateProperty


def types_frame(project_types: list[ProjectType]) -> pd.DataFrame:
    """Preserve the legacy type-table columns, ordering, and integer flag."""
    return pd.DataFrame([
        {**asdict(project_type), "is_general": int(project_type.is_general)}
        for project_type in project_types
    ], columns=["id", "name", "description", "is_general"])


def template_frame(template: list[TemplateProperty]) -> pd.DataFrame:
    """Keep effective-template dataframe construction in presentation."""
    return pd.DataFrame(template)
