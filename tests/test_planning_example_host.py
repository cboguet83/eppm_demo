"""Exercise the shipped session-only example's host handling and launcher."""

import importlib
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Never

import pytest


@pytest.fixture
def example(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the independent example without any application-service imports."""
    monkeypatch.syspath_prepend(str(
        Path(__file__).resolve().parents[1] / "packages/streamlit-planning-view/src",
    ))
    return importlib.import_module("streamlit_planning_view.example")


def event(kind: str, **fields: object) -> dict[str, object]:
    """Build a valid opaque fixture intention."""
    return {"version": 1, "scope": "primary", "revision": "r1",
            "requestId": "request", "type": kind, "targetId": "design",
            "targetKind": "tasks", **fields}


def test_example_accepts_fixture_edits_and_denies_readonly_or_stale_changes(
    example: ModuleType,
) -> None:
    """The example checks its current fixture grant/identity/revision before writes."""
    snapshot = example.initial_snapshot("primary")
    for requested in [event("dates", start="2026-01-02", end="2026-01-06"),
                      event("progress", progress=100),
                      event("task", values={"name": "Accepted", "dependencies": []})]:
        data, responses, status = example.handle_event(snapshot, requested)
        assert responses[0]["accepted"] is True
        assert data["revision"] == "r2"
        assert status == "Change accepted"
    assert snapshot["tasks"][0]["name"] == "Design"
    for requested in [event("task", values={"name": "Reject"}),
                      event("progress", progress=50, targetId="missing"),
                      event("progress", progress=50, revision="old")]:
        _, responses, _ = example.handle_event(snapshot, requested)
        assert responses[0]["accepted"] is False
    readonly = example.initial_snapshot("secondary")
    _, responses, _ = example.handle_event(
        readonly, event("progress", scope="secondary", progress=50),
    )
    assert responses[0]["accepted"] is False
    snapshot["dependencies"] = [{"id": "dep", "type": "FS", "lagDays": 0,
                                 "predecessor": {"kind": "task", "id": "build"},
                                 "successor": {"kind": "task", "id": "design"}}]
    _, responses, _ = example.handle_event(
        snapshot, event("dependency", targetId="dep", targetKind="dependencies",
                        values={"type": "SF", "lagDays": -2}),
    )
    assert responses[0]["accepted"] is True
    data, _, _ = example.handle_event(snapshot, event("task", values={"dependencies": []}))
    assert data["dependencies"] == []


def test_example_lazy_reads_period_selection_and_resource_commands(
    example: ModuleType,
) -> None:
    """Lazy reads are scoped, while resource events retain valid inclusive dates."""
    snapshot = example.initial_snapshot("primary", lazy=True)
    data, patches, status = example.handle_event(snapshot, event("load", projectIds=["alpha"]))
    assert len(data["tasks"]) == 2
    assert patches[0]["replaceProjectIds"] == ["alpha"]
    assert status == "Tasks loaded"
    _, responses, status = example.handle_event(snapshot, event("load", projectIds=["unknown"]))
    assert responses[0]["accepted"] is False
    assert status == "Unknown project"
    context = {"start": "2026-01-01", "end": "2026-01-31"}
    _, _, status = example.handle_event(snapshot, event("select", context=context))
    assert "2026-01-31" in status
    _, _, status = example.handle_event(snapshot, event("select", context=[]))
    assert status == "Selected design"
    data, _, status = example.handle_event(snapshot, event(
        "command", command="mark-period", targetId="engineering", context=context,
    ))
    assert data["resourceFilter"]["end"] == "2026-01-31"
    assert status == "Resource period marked"
    data, _, status = example.handle_event(data, event(
        "command", command="clear-period", targetId="engineering",
    ))
    assert data["resourceFilter"] is None
    assert status == "Resource period cleared"
    _, _, status = example.handle_event(snapshot, event("command", command="other", context=[]))
    assert status == "Unknown resource action"
    assert example.handle_event(snapshot, event("error"))[2] == "No change"
    assert example._period({"start": "bad", "end": "bad"}) is False


class ExampleRerun(RuntimeError):
    """Simulate Streamlit's control transfer without running an app server."""


def test_example_main_initializes_two_keys_reuses_state_and_handles_events(
    example: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped entry point retains two independent sessions and reruns after handling."""
    state: dict[str, object] = {}
    lazy = False

    def rerun() -> None:
        raise ExampleRerun

    fake = SimpleNamespace(
        session_state=state, set_page_config=lambda **kwargs: None,
        title=lambda text: None, caption=lambda text: None,
        subheader=lambda text: None, text=lambda text: None,
        checkbox=lambda *args, **kwargs: lazy, rerun=rerun,
    )
    calls: list[dict[str, object]] = []

    def render(snapshot: object, **options: object) -> None:
        calls.append(options)

    monkeypatch.setattr(example, "st", fake)
    monkeypatch.setattr(example, "planning_view", render)
    example.main()
    example.main()
    assert {call["key"] for call in calls} == {"example-primary", "example-secondary"}
    lazy = True
    example.main()
    assert state["example-data:primary"]["scope"] == "primary-lazy"
    monkeypatch.setattr(example, "planning_view", lambda *args, **kwargs: event(
        "progress", scope="primary-lazy", progress=50,
    ))
    with pytest.raises(ExampleRerun):
        example.main()
    assert state["example-data:primary:status"] == "Change rejected"


def test_installed_example_launcher_uses_current_python_and_safe_arguments(
    example: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI options stay separate subprocess arguments; no shell is used."""
    launcher = importlib.import_module("streamlit_planning_view.__main__")
    calls: list[tuple[str, list[str]]] = []

    def execute(path: str, args: list[str]) -> Never:
        calls.append((path, args))
        raise SystemExit(0)

    monkeypatch.setattr(launcher.os, "execv", execute)
    monkeypatch.setattr(launcher.sys, "argv", ["planning-view", "--server.headless=true"])
    with pytest.raises(SystemExit):
        launcher.main()
    assert calls[0][0] == launcher.sys.executable
    assert calls[0][1][1:4] == ["-m", "streamlit", "run"]
    assert calls[0][1][-1] == "--server.headless=true"
