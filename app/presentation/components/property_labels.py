"""Resolve property display labels without changing stable property identities."""

from collections.abc import Mapping

import pandas as pd
from app.presentation.i18n import t


def parameter_groups(parameters: pd.DataFrame, groups: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    """Use the same ordered property tabs for project creation, editing, and details."""
    if parameters.empty:
        return []
    result = []
    known = set(groups["id"]) if not groups.empty else set()
    for _, group in groups.iterrows():
        fields = parameters[parameters["group_id"] == group["id"]]
        if not fields.empty:
            result.append((str(group["group_name"]), fields))
    other = parameters[parameters["group_id"].isna() | ~parameters["group_id"].isin(known)]
    if not other.empty:
        result.append((t("schema.param_group_none"), other))
    return result


def property_label(parameter: Mapping[str, object], translations: Mapping[str, str]) -> str:
    """Prefer a selected-language alias, then default alias, then property name."""
    translated = translations.get(str(parameter["param_id"]), "").strip()
    alias = parameter.get("alias")
    default = str(alias).strip() if alias is not None and pd.notna(alias) else ""
    return translated or default or str(parameter["param_name"])


def localize_parameters(parameters: pd.DataFrame, translations: Mapping[str, str]) -> pd.DataFrame:
    """Attach resolved display aliases to a copy of the UI's property definitions."""
    result = parameters.copy()
    if not result.empty:
        result["alias"] = [property_label(row, translations) for row in result.to_dict("records")]
    return result
