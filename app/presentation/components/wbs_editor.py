"""WBS draft editing for the planning project popup and read-only details."""

import pandas as pd
import streamlit as st

from app.domain.projects.wbs import WbsAllocation, WbsOption
from app.presentation.i18n import t


def render_wbs_rows(allocations: list[WbsAllocation], options: list[WbsOption]) -> None:
    """Display assigned codes and integer percentages without exposing editing."""
    choices = {row["id"]: row for row in options}
    if not allocations:
        st.info(t("wbs.none"))
        return
    st.dataframe(pd.DataFrame([{t("wbs.code"): choices[row["wbs_id"]]["code"],
                               t("wbs.description"): choices[row["wbs_id"]]["description"],
                               t("wbs.allocation"): row["percentage"]} for row in allocations]).style.set_properties(
                     subset=[t("wbs.code"), t("wbs.allocation")], **{"color": "#808080"}),
                 hide_index=True, width="stretch")


def render_wbs_editor(allocations: list[WbsAllocation], options: list[WbsOption],
                      key: str, *, disabled: bool = False) -> list[WbsAllocation]:
    """Retain row edits in a caller-owned project draft until the project is saved."""
    if disabled:
        render_wbs_rows(allocations, options)
        return allocations
    if not options:
        st.info(t("wbs.empty"))
        return allocations
    labels = {row["id"]: row["code"] + (" — " + row["description"] if row["description"] else "") for row in options}
    identities = {label: identity for identity, label in labels.items()}
    frame = pd.DataFrame([{"code": labels[row["wbs_id"]], "percentage": row["percentage"]}
                          for row in allocations], columns=["code", "percentage"])
    frame["percentage"] = frame["percentage"].astype("Int64")
    edited = st.data_editor(frame, key=key, num_rows="dynamic", hide_index=True, width="stretch",
        column_config={
            "code": st.column_config.SelectboxColumn(t("wbs.code"), options=list(identities), required=True),
            "percentage": st.column_config.NumberColumn(t("wbs.allocation"), min_value=0, max_value=100,
                                                         step=1, default=100, required=True, format="%d%%"),
        })
    result = []
    available = {row["id"]: row for row in options}
    for row in edited.to_dict("records"):
        if row["code"] not in identities:
            continue
        identity = identities[row["code"]]
        percentage = 100 if pd.isna(row["percentage"]) else row["percentage"]
        # The application boundary validates integer values without truncation.
        result.append(WbsAllocation(wbs_id=identity, percentage=percentage))
        st.caption(labels[identity] + " · " + t("wbs.available").replace("{percentage}", str(available[identity]["available"])))
    return result
