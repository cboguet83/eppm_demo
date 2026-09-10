"""Shared finance workspace with browser-local drafts and explicit version saves."""

from dataclasses import asdict
from functools import partial

import streamlit as st

from app.application.exceptions import FinanceStorageError
from app.application.services.finance import FinanceService, FinanceView
from app.domain.access.models import AccessDenied
from app.domain.finance import BudgetRow, FinanceError, euro_text
from app.presentation.components.finance_grid import finance_grid
from app.presentation.i18n import t


LABELS = (
    "version", "empty_plan", "save_as", "revision", "major", "version_name", "save_confirm", "draft_notice",
    "name_required", "save", "add", "reload", "copy_major", "import", "export", "export_saved", "propose", "approve",
    "status_confirm", "status_notice", "metadata", "empty_hint", "grid", "code", "description", "remove",
    "remove_row", "row_count", "unsaved", "saved", "invalid_code", "duplicate_code", "invalid_amount",
    "paste_bounds", "paste_locked", "unmatched", "row_limit", "file_error", "import_preview", "replace_warning",
    "continue", "cancel", "confirm", "discard", "discard_warning", "Draft", "Proposed", "Approved",
)


def _rows(rows: tuple[BudgetRow, ...]) -> list[dict[str, object]]:
    return [{"code": row.code, "amounts": {str(year): euro_text(cents) for year, cents in row.amounts.items()}}
            for row in rows]


def _state() -> dict[str, object]:
    if "finance_ui" not in st.session_state:
        st.session_state["finance_ui"] = {"selected": None, "generation": 0}
    return st.session_state["finance_ui"]


def _action(service: FinanceService, token: str, base_id: int | None) -> None:
    result = st.session_state.get("finance_grid", {})
    action = result.get("action") if isinstance(result, dict) else getattr(result, "action", None)
    state = _state()
    if (not isinstance(action, dict) or action.get("token") != token
            or not isinstance(action.get("nonce"), str) or len(action["nonce"]) > 64
            or state.get("handled") == action["nonce"]):
        return
    state.update(handled=action["nonce"], error="", message="", preview=None)
    try:
        kind = action.get("kind")
        if kind == "save":
            state["selected"] = service.save(action.get("rows"), base_id=base_id, mode=action.get("mode"),
                                              name=action.get("name"), year=action.get("year"))
            state["message"] = t("finance.save_success")
        elif kind == "status" and base_id is not None:
            state["selected"] = service.change_status(base_id, action.get("status"))
            state["message"] = t("finance.save_success")
        elif kind == "select":
            selected = service.view(action.get("snapshot_id")).selected
            state["selected"] = selected.version.id if selected else None
        elif kind == "reload":
            state["selected"] = None
        elif kind == "import":
            rows = service.validate_import(action.get("content"), action.get("year"))
            state["preview"] = {"id": action["nonce"], "rows": _rows(rows)}
            return
        else:
            raise FinanceError("mode")
        state["generation"] += 1
        state.pop("year", None)
    except FinanceError as error:
        state["error"] = t("finance.errors." + error.code, default=str(error), **error.parameters)
    except AccessDenied:
        state["error"] = t("finance.denied")
    except FinanceStorageError:
        state["error"] = t("finance.storage_error")


def _display(view: FinanceView, state: dict[str, object]) -> dict[str, object]:
    selected = view.selected.version if view.selected else None
    latest = next((version for version in view.versions if selected and version.major == selected.major), None)
    year = state.setdefault("year", view.year)
    token = f"{selected.id if selected else 0}:{state['generation']}:{year}"
    return {"token": token, "selected": asdict(selected) if selected else None,
            "versions": [asdict(version) for version in view.versions],
            "rows": _rows(view.selected.rows) if view.selected else [], "catalog": view.catalog,
            "can_edit": view.can_edit, "can_revise": selected is not None and latest.id == selected.id,
            "year": year, "labels": {key: t("finance." + key) for key in LABELS},
            "error": state.get("error", ""), "message": state.get("message", ""), "preview": state.get("preview"),
            "download_url": f"/downloads/finance/{selected.id}/budget.csv" if selected else ""}


@st.fragment
def render_finance(service: FinanceService) -> None:
    """Render an authorized snapshot without rerunning the shell on finance actions."""
    st.header(t("finance.title"))
    st.caption(t("finance.help"))
    state = _state()
    try:
        view = service.view(state["selected"])
        display = _display(view, state)
        state["preview"] = None
        base_id = view.selected.version.id if view.selected else None
        finance_grid(display, partial(_action, service, display["token"], base_id))
    except AccessDenied:
        st.error(t("finance.denied"))
    except FinanceStorageError:
        st.error(t("finance.storage_error"))
    except FinanceError as error:
        st.error(t("finance.errors." + error.code, default=str(error), **error.parameters))
