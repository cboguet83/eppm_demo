"""Focused tests for planning view Gantt interactions."""

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd
import streamlit as st

from app.presentation.pages.planning import (
    _apply_planning_flex_filters,
    _handle_gantt_component_change,
)


class TestPlanningGanttCallbacks(unittest.TestCase):
    """Verify Gantt mutations are persisted in the pre-rerun callback."""

    def tearDown(self) -> None:
        for key in list(st.session_state):
            if (
                str(key).startswith("planning_flex_")
                or key
                in {
                    "active_resource_pool_filter",
                    "last_gantt_nonce",
                    "last_planning_tag_filter",
                    "ms_multi_projects",
                    "ms_planning_tag_filter",
                    "planning_last_flex_signature",
                    "test_gantt",
                }
            ):
                st.session_state.pop(key, None)

    @patch("app.presentation.pages.planning.st.toast")
    def test_drag_update_is_persisted_only_once(self, mock_toast: MagicMock) -> None:
        workspace = MagicMock()
        repo = workspace.planning
        repo.update_dates.return_value = True
        st.session_state["test_gantt"] = {
            "action": "update_dates",
            "id": 42,
            "start_date": "2026-09-10",
            "end_date": "2026-09-18",
            "nonce": "drag-1",
        }

        _handle_gantt_component_change("test_gantt", workspace)
        _handle_gantt_component_change("test_gantt", workspace)

        repo.update_dates.assert_called_once_with(42, "2026-09-10", "2026-09-18")
        self.assertEqual(st.session_state["last_gantt_nonce"], "drag-1")
        mock_toast.assert_called_once()

    @patch("app.presentation.pages.planning.st.toast")
    def test_progress_update_is_persisted_before_render(self, mock_toast: MagicMock) -> None:
        workspace = MagicMock()
        repo = workspace.planning
        repo.update_progress.return_value = True
        st.session_state["test_gantt"] = {
            "action": "update_progress",
            "id": "7",
            "progress": 100,
            "nonce": "progress-1",
        }

        _handle_gantt_component_change("test_gantt", workspace)

        repo.update_progress.assert_called_once_with(7, 100)
        mock_toast.assert_called_once()

    def test_unrelated_event_remains_for_the_regular_handler(self) -> None:
        workspace = MagicMock()
        repo = workspace.planning
        st.session_state["test_gantt"] = {
            "action": "manage_task_tags",
            "id": 7,
            "nonce": "menu-1",
        }

        _handle_gantt_component_change("test_gantt", workspace)

        repo.assert_not_called()
        self.assertNotIn("last_gantt_nonce", st.session_state)

    @patch("app.presentation.pages.planning.st.toast")
    def test_context_menu_filter_focuses_one_project(self, mock_toast: MagicMock) -> None:
        workspace = MagicMock()
        repo = workspace.planning
        st.session_state["test_gantt"] = {
            "action": "filter_project",
            "project_id": "12",
            "project_name": "New Campus",
            "nonce": "filter-1",
        }
        st.session_state["active_resource_pool_filter"] = {"pool_id": 3}
        st.session_state["planning_flex_fields"] = ["Status"]
        st.session_state["planning_flex_values::status"] = ["Active"]
        st.session_state["ms_planning_tag_filter"] = ["Priority"]

        _handle_gantt_component_change("test_gantt", workspace)

        self.assertEqual(st.session_state["ms_multi_projects"], [12])
        self.assertEqual(st.session_state["ms_planning_tag_filter"], [])
        self.assertNotIn("active_resource_pool_filter", st.session_state)
        self.assertNotIn("planning_flex_fields", st.session_state)
        self.assertNotIn("planning_flex_values::status", st.session_state)
        self.assertEqual(st.session_state["last_gantt_nonce"], "filter-1")
        repo.assert_not_called()
        mock_toast.assert_called_once_with("Filtered planning to New Campus", icon="🔍")

    def test_flexible_filters_use_and_between_fields(self) -> None:
        frame = pd.DataFrame(
            [
                {"id": 1, "status": "Active", "tags": ["North", "Priority"]},
                {"id": 2, "status": "Active", "tags": ["South"]},
                {"id": 3, "status": "Draft", "tags": ["North"]},
            ]
        )

        result = _apply_planning_flex_filters(
            frame,
            {"status": ["active"], "tags": ["north", "priority"]},
        )
        all_values_result = _apply_planning_flex_filters(
            frame,
            {"tags": ["north", "priority"]},
            match_all_values=True,
        )

        self.assertEqual(result["id"].tolist(), [1])
        self.assertEqual(all_values_result["id"].tolist(), [1])


if __name__ == "__main__":
    unittest.main()
