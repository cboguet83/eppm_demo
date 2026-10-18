"""Safe JSON/event boundaries for the independent Streamlit transport.

The browser owns full rendering schema validation. Python validates transport
envelopes and all event fields before exposing them to a host application.
"""

from collections.abc import Mapping
from datetime import date
import json
import math
import re
from typing import cast

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)
type JsonObject = dict[str, JsonValue]

CONTRACT_VERSION = 1
EVENT_TYPES = frozenset({
    "dates", "progress", "task", "dependency", "select", "command", "load",
    "error",
})
TARGET_TYPES = frozenset({
    "tasks", "projects", "dependencies", "resources", "hierarchy",
})


class PlanningContractError(ValueError):
    """Indicate an invalid transport value without echoing supplied data."""


def _require(condition: bool, path: str) -> None:
    if not condition:
        raise PlanningContractError(f"Invalid planning contract at {path}")


def _text(value: JsonValue, path: str) -> None:
    _require(isinstance(value, str) and bool(value.strip()), path)


def _date(value: JsonValue, path: str) -> date:
    _require(
        isinstance(value, str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None,
        path,
    )
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise PlanningContractError(
            f"Invalid planning contract at {path}",
        ) from None


def _range(value: JsonObject) -> None:
    first = _date(value.get("start"), "start")
    last = _date(value.get("end"), "end")
    _require(first <= last, "range")


def _progress(value: JsonValue) -> None:
    _require(
        type(value) in (int, float)
        and math.isfinite(value) and 0 <= value <= 100,
        "progress",
    )


def _dependency(value: JsonValue, *, partial: bool = False) -> None:
    _require(isinstance(value, dict), "dependency")
    if not partial or "type" in value:
        _require(
            value.get("type") in ("FS", "SS", "FF", "SF"), "dependency.type",
        )
    if "lagDays" in value:
        _require(type(value["lagDays"]) is int, "dependency.lagDays")
    for side in ("predecessor", "successor"):
        if partial and side not in value:
            continue
        endpoint = value.get(side)
        _require(isinstance(endpoint, dict), f"dependency.{side}")
        _require(
            endpoint.get("kind") in ("project", "task", "unavailable"),
            "endpoint.kind",
        )
        if endpoint["kind"] != "unavailable":
            _text(endpoint.get("id"), "endpoint.id")


def _envelope(value: JsonObject) -> None:
    _require(
        type(value.get("version")) is int
        and value["version"] == CONTRACT_VERSION,
        "version",
    )
    _text(value.get("scope"), "scope")
    _text(value.get("revision"), "revision")


def json_object(value: Mapping[str, JsonValue]) -> JsonObject:
    """Copy JSON safely, rejecting cycles and nonfinite values.

    Args:
        value: Transport data supplied by an application or component.

    Returns:
        A JSON-owned dictionary.

    Raises:
        PlanningContractError: Data cannot be represented by the JSON contract.
    """
    _require(isinstance(value, Mapping), "object")
    value = dict(value)
    pending: list[JsonValue] = [value]
    visited: set[int] = set()
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            _require(all(isinstance(key, str) for key in item), "json.keys")
        if isinstance(item, (dict, list)):
            if id(item) in visited:
                # json.dumps rejects cycles but permits shared JSON values.
                continue
            visited.add(id(item))
            pending.extend(item.values() if isinstance(item, dict) else item)
        else:
            _require(type(item) in (str, int, float, bool, type(None)), "json")
    try:
        return cast(JsonObject, json.loads(json.dumps(value, allow_nan=False)))
    except (TypeError, ValueError, RecursionError):
        raise PlanningContractError(
            "Invalid planning contract at json",
        ) from None


def validate_message(value: Mapping[str, JsonValue]) -> JsonObject:
    """Validate a component update envelope before passing JSON to the browser.

    Args:
        value: Snapshot, patch, or correlated response.

    Returns:
        Owned JSON with a supported envelope.

    Raises:
        PlanningContractError: The envelope or required collection is invalid.
    """
    result = json_object(value)
    _envelope(result)
    _require(result.get("kind") in ("snapshot", "patch", "response"), "kind")
    if result["kind"] == "snapshot":
        _require(isinstance(result.get("projects"), list), "projects")
        _require(isinstance(result.get("tasks"), list), "tasks")
    if result["kind"] == "response":
        _text(result.get("requestId"), "requestId")
        _require(isinstance(result.get("accepted"), bool), "accepted")
        _require(
            "error" not in result or isinstance(result["error"], str), "error",
        )
    return result


def _edit_values(result: JsonObject) -> None:
    event_type = result["type"]
    if event_type == "dates":
        _range(result)
    if event_type == "progress":
        _progress(result.get("progress"))
    if event_type not in ("task", "dependency"):
        return
    values = result.get("values")
    _require(isinstance(values, dict), "values")
    if event_type == "dependency":
        _dependency(values, partial=True)
        return
    if "start" in values or "end" in values:
        _range(values)
    if "progress" in values:
        _progress(values["progress"])
    for field in ("name", "description", "phase"):
        _require(
            field not in values or isinstance(values[field], str),
            f"values.{field}",
        )
    if "dependencies" in values:
        _require(
            isinstance(values["dependencies"], list), "values.dependencies",
        )
        for dependency in values["dependencies"]:
            _dependency(dependency)


def validate_event(value: Mapping[str, JsonValue]) -> JsonObject:
    """Validate a user intention before returning it to application code.

    Args:
        value: Untrusted component JSON that still needs host authorization.

    Returns:
        An owned event preserving opaque identities and inclusive dates.

    Raises:
        PlanningContractError: A required event field or value is invalid.
    """
    result = json_object(value)
    _envelope(result)
    _text(result.get("requestId"), "requestId")
    _require(isinstance(result.get("type"), str), "type")
    _require(result["type"] in EVENT_TYPES, "type")
    if result["type"] in ("dates", "progress", "task", "dependency", "select"):
        _text(result.get("targetId"), "targetId")
        _require(isinstance(result.get("targetKind"), str), "targetKind")
        _require(result["targetKind"] in TARGET_TYPES, "targetKind")
    if result["type"] == "command":
        _text(result.get("command"), "command")
    if result["type"] == "load":
        ids = result.get("projectIds")
        _require(isinstance(ids, list), "projectIds")
        for identity in ids:
            _text(identity, "projectIds")
        _require(len(set(ids)) == len(ids), "projectIds")
    _edit_values(result)
    return result
