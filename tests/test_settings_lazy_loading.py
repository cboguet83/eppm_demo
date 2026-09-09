"""Exercise real Streamlit reruns to ensure hidden tabs do not load data."""

from app.presentation.components import resource_pool_frames

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.infrastructure.database.seeder import seed_default_data_if_empty


def settings_app(db_path):
    from app.main import create_settings_workspace
    from app.presentation.pages.settings import render_settings_view
    render_settings_view(create_settings_workspace(db_path))


class SettingsLazyLoadingTests(unittest.TestCase):
    def test_resource_pool_details_keep_controls_without_daily_chart(self) -> None:
        """Pools with and without demand retain details but never render a chart."""
        from app.domain.resources.models import ResourcePool
        from app.main import create_resource_pool_service

        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            seed_default_data_if_empty(db_path)
            pools = create_resource_pool_service(db_path)
            assigned_pool_id = int(resource_pool_frames.assignments_frame(pools.get_assignments()).iloc[0]["pool_id"])
            empty_pool_id = pools.create_pool(
                ResourcePool(name="Pool without demand", capacity_fte=3.0)
            )
            app = AppTest.from_function(settings_app, args=(db_path,))
            app.session_state["settings_active_tab"] = "resource_pools"
            with patch("app.presentation.pages.settings.st.plotly_chart",
                       side_effect=AssertionError("Removed daily chart rendered")):
                for pool_id in (assigned_pool_id, empty_pool_id):
                    with self.subTest(pool_id=pool_id):
                        app.session_state["target_resource_pool_id"] = pool_id
                        app.run()
                        self.assertEqual(list(app.exception), [])
                        self.assertEqual(app.session_state["sb_selected_resource_pool"], pool_id)
                        self.assertEqual(len(app.metric), 5)
                        self.assertTrue(app.success or app.error, "Capacity status remains visible")
                        button_keys = {button.key for button in app.button}
                        self.assertIn(f"btn_edit_pool_{pool_id}", button_keys)
                        self.assertIn(f"btn_add_map_{pool_id}", button_keys)
                        markup = "\n".join(item.value for item in app.markdown)
                        self.assertNotIn("Daily Capacity vs. Assigned Demand Timeline", markup)
                        self.assertIn("Active Allocations on Projects & Tasks", markup)
                        self.assertIn("Deduplicated Assigned Capacity Breakdown", markup)
                        if pool_id == assigned_pool_id:
                            self.assertIn("?nav=planning&project_id=", markup)

    def test_pool_data_is_loaded_only_in_pool_tab_and_selection_survives_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            seed_default_data_if_empty(db_path)
            app = AppTest.from_function(settings_app, args=(db_path,))
            with patch("app.application.services.pool_capacity.PoolCapacityService.get_summaries", side_effect=AssertionError("Hidden pools loaded")):
                app.run()
                self.assertEqual(list(app.exception), [])
            app.session_state["settings_active_tab"] = "resource_pools"
            with patch("app.application.services.tags.TagService.get_task_tags_page",
                       side_effect=AssertionError("Hidden task tab loaded")):
                app.run()
                self.assertEqual(list(app.exception), [])
                self.assertIn("Resource Pools", app.session_state["settings_tab_selection"])
                app.run()
                self.assertEqual(list(app.exception), [])
                self.assertIn("Resource Pools", app.session_state["settings_tab_selection"])
