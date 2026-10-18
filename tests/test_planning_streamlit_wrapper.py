"""Validate the independent Python wrapper without EPPM services or persistence."""

from collections.abc import Callable
import importlib
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import cast

import pytest


class RecordingComponent:
    """Record one real component boundary while returning controlled JSON."""

    calls: list[dict[str, object]]
    value: object

    def __init__(self) -> None:
        self.calls = []
        self.value = None

    def __call__(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.value


@pytest.fixture
def wrapper(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import only the standalone package and isolate its Streamlit session."""
    source = Path(__file__).resolve().parents[1] / "packages/streamlit-planning-view/src"
    monkeypatch.syspath_prepend(str(source))
    module = importlib.import_module("streamlit_planning_view")
    monkeypatch.setattr(module.st, "session_state", {})
    return module


def snapshot() -> dict[str, object]:
    """Return a minimal opaque contract snapshot."""
    return {"version": 1, "kind": "snapshot", "scope": "s", "revision": "r",
            "projects": [], "tasks": []}


def event(event_type: str = "select", **extra: object) -> dict[str, object]:
    """Return an intention with a stable request identity."""
    return {"version": 1, "scope": "s", "revision": "r", "requestId": "opaque",
            "type": event_type, "targetId": "task", "targetKind": "tasks", **extra}


def test_wrapper_acknowledges_before_render_and_delivers_once_per_key(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The callback prepares acknowledgements while the host receives each event once."""
    component = RecordingComponent()
    monkeypatch.setattr(wrapper, "_component", lambda: component)
    assert wrapper.planning_view(snapshot(), key="first") is None
    value = event()
    wrapper.st.session_state["first"] = value
    cast(Callable[[], None], component.calls[-1]["on_change"])()
    component.value = value
    assert wrapper.planning_view(snapshot(), key="first") == value
    assert component.calls[-1]["ackRequestIds"] == ["opaque"]
    assert wrapper.planning_view(snapshot(), key="first") is None
    assert wrapper.planning_view(snapshot(), key="second") == value
    assert wrapper.planning_view(snapshot(), key="second") is None


def test_wrapper_filters_stale_scope_and_revision_and_bounds_acknowledgements(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old intentions are acknowledged safely without applying to another view."""
    component = RecordingComponent()
    monkeypatch.setattr(wrapper, "_component", lambda: component)
    wrapper.planning_view(snapshot(), key="first")
    wrapper.st.session_state["first"] = event()
    cast(Callable[[], None], component.calls[-1]["on_change"])()
    component.value = event()
    assert wrapper.planning_view({**snapshot(), "scope": "other"}, key="first") is None
    component.value = event(requestId="old-revision")
    assert wrapper.planning_view({**snapshot(), "revision": "next"}, key="first") is None
    for index in range(260):
        component.value = event(requestId=str(index), revision="next")
        wrapper.planning_view({**snapshot(), "revision": "next"}, key="first")
    assert len(wrapper._state("first")["acks"]) == 256


def test_wrapper_transports_lazy_patches_options_and_safe_correlated_responses(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read/action responses remain JSON and preserve their request identity."""
    component = RecordingComponent()
    component.value = event("load", projectIds=["project-alpha"])
    monkeypatch.setattr(wrapper, "_component", lambda: component)
    patch = {**snapshot(), "kind": "patch", "requestId": "read",
             "replaceProjectIds": ["project-alpha"], "tasks": []}
    response = {**snapshot(), "kind": "response", "requestId": "edit",
                "accepted": False, "error": "Conflict"}
    value = wrapper.planning_view(
        snapshot(), key="first", lazy=True, updates=[patch, response],
        options={"mode": "Month"},
    )
    assert value["type"] == "load"
    assert component.calls[-1]["messages"] == [patch, response]
    assert component.calls[-1]["lazy"] is True
    assert component.calls[-1]["options"] == {"mode": "Month"}


@pytest.mark.parametrize("kwargs", [
    {"key": ""}, {"key": 1}, {"key": "k", "lazy": "yes"},
    {"key": "k", "options": {"bad": object()}},
])
def test_invalid_wrapper_arguments_fail_before_component_delivery(
    wrapper: ModuleType, kwargs: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject malformed boundary values without rendering or leaking input."""
    component = RecordingComponent()
    monkeypatch.setattr(wrapper, "_component", lambda: component)
    with pytest.raises(wrapper.PlanningContractError):
        wrapper.planning_view(snapshot(), **kwargs)
    assert component.calls == []
    with pytest.raises(wrapper.PlanningContractError):
        wrapper.planning_view({**snapshot(), "kind": "patch"}, key="k")


def test_component_factory_requires_assets_and_caches_one_declaration(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Runtime registration requires a prepared frontend and happens once."""
    wrapper._component.cache_clear()
    monkeypatch.setattr(wrapper, "__file__", str(tmp_path / "__init__.py"))
    with pytest.raises(RuntimeError, match="frontend assets are missing"):
        wrapper._component()
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html>", encoding="utf-8")
    component = RecordingComponent()
    declarations: list[tuple[str, str]] = []

    def declare(name: str, path: str) -> RecordingComponent:
        declarations.append((name, path))
        return component

    monkeypatch.setattr(wrapper, "declare_component", declare)
    assert wrapper._component() is wrapper._component()
    assert declarations == [("planning_view", str(frontend))]
    wrapper._component.cache_clear()


@pytest.mark.parametrize("changes", [
    {"version": 2}, {"version": True}, {"scope": ""}, {"revision": 1},
    {"requestId": ""}, {"type": []}, {"type": "unknown"},
    {"targetId": 1}, {"targetKind": []}, {"targetKind": "unknown"},
])
def test_event_envelope_rejects_malformed_fields(
    wrapper: ModuleType, changes: dict[str, object],
) -> None:
    """Validate untrusted identities and event codes before host handling."""
    with pytest.raises(wrapper.PlanningContractError):
        wrapper.validate_event({**event(), **changes})


@pytest.mark.parametrize(("event_type", "values"), [
    ("dates", {"start": "2027-02-29", "end": "2027-03-01"}),
    ("dates", {"start": "2026-01-03", "end": "2026-01-01"}),
    ("dates", {"start": 1, "end": "2026-01-01"}),
    ("progress", {"progress": True}), ("progress", {"progress": 101}),
    ("command", {"command": ""}), ("load", {"projectIds": "project"}),
    ("load", {"projectIds": ["p", "p"]}), ("load", {"projectIds": [1]}),
    ("task", {"values": []}), ("task", {"values": {"description": 1}}),
    ("task", {"values": {"dependencies": {}}}),
    ("task", {"values": {"dependencies": [1]}}),
    ("dependency", {"values": {"type": "invalid"}}),
    ("dependency", {"values": {"lagDays": 1.5}}),
    ("dependency", {"values": {"predecessor": []}}),
    ("dependency", {"values": {"predecessor": {"kind": "wrong"}}}),
    ("dependency", {"values": {"predecessor": {"kind": "task", "id": 1}}}),
])
def test_event_values_reject_invalid_calendar_progress_and_dependencies(
    wrapper: ModuleType, event_type: str, values: dict[str, object],
) -> None:
    """Malformed edit/load values fail safely before application interpretation."""
    with pytest.raises(wrapper.PlanningContractError):
        wrapper.validate_event(event(event_type, **values))


def test_valid_event_values_and_json_ownership(wrapper: ModuleType) -> None:
    """Retain leap dates, opaque targets, zeroes and independently owned JSON."""
    contracts = importlib.import_module("streamlit_planning_view.contracts")
    dependency = {"id": "d", "type": "SF", "lagDays": -2,
                  "predecessor": {"kind": "unavailable"},
                  "successor": {"kind": "project", "id": "project-alpha"}}
    for value in [
        event("dates", start="2028-02-29", end="2028-03-01"),
        event("progress", progress=0), event("command", command="host"),
        event("task", values={"start": "2028-02-29", "end": "2028-03-01",
                              "progress": 100, "name": "Safe",
                              "dependencies": [dependency]}),
        event("dependency", values=dependency), event("error"),
        event("dependency", values={"lagDays": 1}),
    ]:
        assert wrapper.validate_event(value) == value
    child: dict[str, object] = {"zero": 0}
    source = {"one": child, "two": child}
    result = contracts.json_object(MappingProxyType(source))
    child["zero"] = 10
    assert result["one"]["zero"] == 0
    cycle: dict[str, object] = {}
    cycle["self"] = cycle
    for value in [cycle, {"bad": float("nan")}, {"bad": object()}, {1: "bad"}]:
        with pytest.raises(wrapper.PlanningContractError, match="at json"):
            contracts.json_object(value)


@pytest.mark.parametrize("changes", [
    {"kind": "unknown"}, {"projects": {}}, {"tasks": {}},
    {"kind": "response", "requestId": "r", "accepted": 1},
    {"kind": "response", "requestId": "r", "accepted": False, "error": 1},
])
def test_message_boundary_rejects_invalid_envelopes(
    wrapper: ModuleType, changes: dict[str, object],
) -> None:
    """Transport cannot send unsupported kinds or invalid action responses."""
    with pytest.raises(wrapper.PlanningContractError):
        wrapper.validate_message({**snapshot(), **changes})
