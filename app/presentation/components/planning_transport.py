"""Bounded task batches and lossless daily-pool encoding for the chart wire."""

from datetime import date
from hashlib import sha256
from typing import Any
from app.application.exceptions import PlanningRevisionChanged

from app.presentation.components.planning_data import build_task_payload
from app.presentation.components.planning_workspace import PlanningWorkspace


def pack_pool_payloads(pools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Encode the dynamic chart JSON boundary without dropping zeroes or gaps."""
    result = []
    for pool in pools:
        packed = dict(pool)
        packed.pop("overallocated_dates", None)
        packed.pop("selected_projects_overallocated_dates", None)
        for field in ("daily_usage", "daily_assigned_capacity", "selected_projects_daily_usage"):
            intervals = []
            previous = None
            for day, value in sorted(packed.pop(field, {}).items()):
                ordinal = date.fromisoformat(day).toordinal()
                if intervals and ordinal == previous + 1 and intervals[-1][2] == value:
                    intervals[-1][1] = day
                else:
                    intervals.append([day, day, value])
                previous = ordinal
            packed[field + "_intervals"] = intervals
        result.append(packed)
    return result


def planning_revision_token(revision: tuple) -> str:
    """Expose a digest, rather than internal session or database identifiers."""
    return sha256(repr(revision).encode("utf-8")).hexdigest()


def read_planning_batch(workspace: PlanningWorkspace, project_ids: list[int], revision: str) -> dict[str, object]:
    """Build one task batch and reject data changed or revoked during its reads."""
    current = workspace.revision()
    if planning_revision_token(current) != revision:
        raise PlanningRevisionChanged()
    ids = tuple(sorted(project_ids))
    bundle = workspace.planning.read_task_bundle(list(ids))
    tasks = build_task_payload(workspace, ids, bundle.project_bounds, bundle=bundle)
    result = {
        "replace_projects": project_ids,
        "tasks": tasks,
        "project_metadata": [{"id": str(pid), "tags": bundle.project_tags.get(pid, []),
                              "pools": bundle.project_pools.get(pid, [])} for pid in ids],
    }
    if workspace.revision() != current:
        raise PlanningRevisionChanged()
    return result
