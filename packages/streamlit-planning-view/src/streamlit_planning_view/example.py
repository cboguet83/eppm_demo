"""Runnable fixture host demonstrating independent planning integration."""

from datetime import date
from typing import cast
from uuid import uuid4

import streamlit as st

from streamlit_planning_view import planning_view
from streamlit_planning_view.contracts import (
    JsonObject, JsonValue, json_object, validate_event,
)


def initial_snapshot(scope: str, *, lazy: bool = False) -> JsonObject:
    """Build example data with opaque IDs and optional lazy reads.

    Args:
        scope: Independent view identity.
        lazy: Supply project summaries before requesting task data.

    Returns:
        A contract-v1 snapshot containing no application/service imports.
    """
    snapshot: JsonObject = {
        "version": 1, "kind": "snapshot", "scope": scope, "revision": "r1",
        "capabilities": {"edit": scope.startswith("primary"),
                         "createDependencies": scope.startswith("primary")},
        "projects": [{"id": "alpha", "name": "Alpha", "taskCount": 2,
                      "start": "2026-01-01", "end": "2026-12-31"}],
        "tasks": [
            {"id": "design", "projectId": "alpha", "name": "Design",
             "start": "2026-01-01", "end": "2026-01-05", "progress": 20},
            {"id": "build", "projectId": "alpha", "name": "Build",
             "start": "2026-02-01", "end": "2026-12-31", "progress": 0},
        ],
        "dependencies": [],
        "resources": [{"id": "engineering", "name": "Engineering",
                       "capacity": 10, "usage": {"2026-01-01": 6},
                       "selectedUsage": {"2026-01-01": 3}}],
    }
    if lazy:
        snapshot.update(tasks=[], loadedProjectIds=[])
    return snapshot


def _response(
    data: JsonObject, event: JsonObject, accepted: bool,
) -> JsonObject:
    result: JsonObject = {
        "version": 1, "kind": "response", "scope": data["scope"],
        "revision": data["revision"], "requestId": event["requestId"],
        "accepted": accepted,
    }
    if not accepted:
        result["error"] = "The example rejected this change."
    return result


def _period(context: JsonObject) -> bool:
    try:
        start, end = str(context["start"]), str(context["end"])
        return (date.fromisoformat(start).isoformat() == start
                and date.fromisoformat(end).isoformat() == end
                and start <= end)
    except (KeyError, ValueError):
        return False


def handle_event(
    snapshot: JsonObject, event: JsonObject,
) -> tuple[JsonObject, list[JsonObject], str]:
    """Apply authorized fixture intentions or return a safe rejection.

    Args:
        snapshot: This example session's authoritative fixture data.
        event: Untrusted browser intention, validated again before handling.

    Returns:
        Updated fixture, correlated updates and human-readable status.

    Raises:
        PlanningContractError: The event violates its transport schema.
    """
    data, received = json_object(snapshot), validate_event(event)
    if (received["scope"], received["revision"]) != (
        data["scope"], data["revision"],
    ):
        return data, [_response(data, received, False)], "View changed"
    if received["type"] == "load":
        ids = cast(list[str], received["projectIds"])
        projects = cast(list[JsonObject], data["projects"])
        if not set(ids).issubset({project["id"] for project in projects}):
            return data, [_response(data, received, False)], "Unknown project"
        tasks = cast(list[JsonObject], initial_snapshot("primary")["tasks"])
        tasks = [task for task in tasks if task["projectId"] in ids]
        data.update(tasks=tasks, loadedProjectIds=cast(list[JsonValue], ids))
        return data, [{
            "version": 1, "kind": "patch", "scope": data["scope"],
            "revision": data["revision"], "requestId": received["requestId"],
            "replaceProjectIds": cast(list[JsonValue], ids), "tasks": tasks,
        }], "Tasks loaded"
    if received["type"] == "select":
        context = received.get("context", {})
        if not isinstance(context, dict):
            context = {}
        label = str(received["targetId"])
        if _period(context):
            label += " · " + str(context["start"])
            label += " → " + str(context["end"])
        return data, [], "Selected " + label
    if received["type"] == "command":
        context = received.get("context", {})
        if not isinstance(context, dict):
            context = {}
        known = any(resource["id"] == received.get("targetId")
                    for resource in cast(list[JsonObject], data["resources"]))
        if received["command"] == "mark-period" and known and _period(context):
            data["resourceFilter"] = {
                "resourceId": received["targetId"], "name": "Engineering",
                "start": context["start"], "end": context["end"],
                "clearAction": "clear-period",
            }
            return data, [], "Resource period marked"
        if received["command"] == "clear-period" and known:
            data["resourceFilter"] = None
            return data, [], "Resource period cleared"
        return data, [], "Unknown resource action"
    if received["type"] not in ("dates", "progress", "task", "dependency"):
        return data, [], "No change"
    values = cast(JsonObject, received.get("values", received))
    if received['type'] == 'dependency' and received.get('operation') == 'create':
        return _create_dependency(data, received, values)
    collection = ("dependencies" if received["type"] == "dependency"
                  else "tasks")
    rows = cast(list[JsonObject], data[collection])
    target = next(
        (row for row in rows if row["id"] == received["targetId"]), None,
    )
    grants = cast(JsonObject, data["capabilities"])
    if (not grants.get("edit") or target is None
            or values.get("name") == "Reject"):
        return data, [_response(data, received, False)], "Change rejected"
    allowed = (("type", "lagDays", "predecessor", "successor")
               if collection == "dependencies" else
               ("name", "start", "end", "progress", "description", "phase"))
    target.update({field: values[field] for field in allowed
                   if field in values})
    if received["type"] == "task" and "dependencies" in values:
        incoming = cast(list[JsonObject], values["dependencies"])
        existing = cast(list[JsonObject], data["dependencies"])
        data["dependencies"] = [
            dep for dep in existing
            if cast(JsonObject, dep["successor"]).get("id") != target["id"]
        ] + incoming
    data["revision"] = "r" + str(int(str(data["revision"])[1:]) + 1)
    return data, [_response(data, received, True)], "Change accepted"


def _create_dependency(
    data: JsonObject, event: JsonObject, values: JsonObject,
) -> tuple[JsonObject, list[JsonObject], str]:
    """Append a fixture link only when both endpoints exist and editing is allowed."""
    grants = cast(JsonObject, data['capabilities'])
    for side in ('predecessor', 'successor'):
        endpoint = cast(JsonObject, values[side])
        rows = cast(list[JsonObject], data['tasks' if endpoint['kind'] == 'task' else 'projects'])
        if not any(row['id'] == endpoint['id'] for row in rows):
            return data, [_response(data, event, False)], 'Unknown endpoint'
    if not grants.get('edit') or not grants.get('createDependencies'):
        return data, [_response(data, event, False)], 'Change rejected'
    dependencies = cast(list[JsonObject], data['dependencies'])
    dependencies.append({'id': str(uuid4()), **values})
    data['revision'] = 'r' + str(int(str(data['revision'])[1:]) + 1)
    return data, [_response(data, event, True)], 'Dependency created'


def main() -> None:
    """Render two keyed examples with session-owned fixture data."""
    st.set_page_config(page_title="Planning view example", layout="wide")
    st.title("Planning view")
    st.caption(
        "Edits update this Streamlit session. Use Reject as a task name "
        "to see a host rejection.",
    )
    lazy = st.checkbox("Load tasks on demand", key="example-lazy")
    for key in ("primary", "secondary"):
        scope = key + ("-lazy" if key == "primary" and lazy else "-full")
        state_key = "example-data:" + key
        if (state_key not in st.session_state
                or st.session_state[state_key]["scope"] != scope):
            st.session_state[state_key] = initial_snapshot(
                scope, lazy=key == "primary" and lazy,
            )
            st.session_state[state_key + ":updates"] = []
            st.session_state[state_key + ":status"] = "Ready"
        st.subheader(key)
        received = planning_view(
            st.session_state[state_key], key="example-" + key,
            lazy=key == "primary" and lazy,
            updates=st.session_state[state_key + ":updates"],
            options={"today": "2026-01-01", "mode": "Day", "grouped": False,
                     "editEnabled": True, "contextActions": [
                         {"id": "mark-period", "label": "Mark resource period",
                          "targetKinds": ["resources"]},
                         {"id": "clear-period", "label": "Clear marked period",
                          "targetKinds": ["resources"]},
                     ]},
        )
        if received:
            data, updates, status = handle_event(
                st.session_state[state_key], received,
            )
            st.session_state[state_key] = data
            st.session_state[state_key + ":updates"] = updates
            st.session_state[state_key + ":status"] = status
            st.rerun()
        st.text(st.session_state[state_key + ":status"])


if __name__ == "__main__":
    main()
