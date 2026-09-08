"""Existing tag-table assets registered in the active Streamlit runtime."""

from app.presentation.assets import component_path
from typing import Any, Literal

import streamlit.components.v1 as components

type TagTable = Literal[
    "tag_group_table", "tag_dictionary_table", "project_tag_table", "task_tag_table"
]


def _render(kind: TagTable, payload: dict[str, Any]) -> Any:
    """Adapt dynamic component JSON; application/domain APIs remain typed."""
    path = component_path(kind)
    component = components.declare_component("interactive_" + kind, path=str(path))
    return component(**payload)


def interactive_tag_group_table(**payload: Any) -> Any:
    """Render group records and consume the component's dynamic event payload."""
    return _render("tag_group_table", payload)


def interactive_tag_dictionary_table(**payload: Any) -> Any:
    """Render dictionary records and consume the component's dynamic event payload."""
    return _render("tag_dictionary_table", payload)


def interactive_project_tag_table(**payload: Any) -> Any:
    """Render project assignments and consume the component's dynamic event payload."""
    return _render("project_tag_table", payload)


def interactive_task_tag_table(**payload: Any) -> Any:
    """Render one task-tag page and consume the component's dynamic event payload."""
    return _render("task_tag_table", payload)
