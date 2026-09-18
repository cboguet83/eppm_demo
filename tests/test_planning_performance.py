"""Direct organization label lookup is built once for a project batch."""

import unittest
from unittest.mock import patch

import pandas as pd

from app.presentation.components.planning_catalog import get_function_occupant_names, enrich_projects_with_organization


class PlanningHierarchyPerformanceTests(unittest.TestCase):
    """Keep direct-manager lookup performance independent of persistence."""

    def test_direct_manager_index_is_built_once_without_traversing_parent_links(self):
        functions = pd.DataFrame([
            {"function_id": 1, "name": "Director", "manager_function_id": None},
            {"function_id": 2, "name": "Service", "manager_function_id": 1},
            {"function_id": 3, "name": "Manager", "manager_function_id": 2},
            {"function_id": 4, "name": "Loop", "manager_function_id": 4},
        ])
        projects = pd.DataFrame({"function_id": [1, 2, 3, 4, None, 99] * 100})
        employees = pd.DataFrame([{"function_id": 3, "firstname": "Ada", "lastname": "Lovelace"}])
        with patch("app.presentation.components.planning_catalog.get_function_occupant_names",
                          wraps=get_function_occupant_names) as build:
            result = enrich_projects_with_organization(projects, functions, employees)
        build.assert_called_once()
        self.assertNotIn("level_3_manager_name", result.columns)
        self.assertEqual(result["project_manager"].iloc[2], "Ada Lovelace")
        self.assertEqual(result["project_manager"].iloc[1], "Service")
