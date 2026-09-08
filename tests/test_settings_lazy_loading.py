"""Exercise real Streamlit reruns to ensure hidden tabs do not load data."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.database.seeder import seed_default_data_if_empty


def settings_app(db_path):
    from src.repositories.organization_repo import OrganizationRepository
    from src.views.settings_view import render_settings_view
    render_settings_view(OrganizationRepository(db_path))


class SettingsLazyLoadingTests(unittest.TestCase):
    def test_pool_data_is_loaded_only_in_pool_tab_and_selection_survives_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            seed_default_data_if_empty(db_path)
            app = AppTest.from_function(settings_app, args=(db_path,))
            with patch("src.services.pool_capacity_cache.load_pool_capacities", side_effect=AssertionError("Hidden pools loaded")):
                app.run()
                self.assertEqual(list(app.exception), [])
            app.session_state["settings_active_tab"] = "resource_pools"
            with patch("src.repositories.milestone_repo.MilestoneRepository.get_all_milestones",
                       side_effect=AssertionError("Hidden task tab loaded")):
                app.run()
                self.assertEqual(list(app.exception), [])
                self.assertIn("Resource Pools", app.session_state["settings_tab_selection"])
                app.run()
                self.assertEqual(list(app.exception), [])
                self.assertIn("Resource Pools", app.session_state["settings_tab_selection"])
