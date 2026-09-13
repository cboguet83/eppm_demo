"""Bounded organization lookup construction and cycle-safe enrichment."""

import unittest
from unittest.mock import patch

import pandas as pd

from app.presentation.components.planning_catalog import _build_function_lookup, enrich_projects_with_organization


class PlanningHierarchyPerformanceTests(unittest.TestCase):
    """Keep hierarchy lookup performance independent of persistence."""

    def test_hierarchy_index_is_built_once_and_loops_are_safe(self):
        functions = pd.DataFrame([
            {"function_id": 1, "name": "Director", "hierarchy_level": 2, "manager_function_id": None},
            {"function_id": 2, "name": "Service", "hierarchy_level": 3, "manager_function_id": 1},
            {"function_id": 3, "name": "Manager", "hierarchy_level": 4, "manager_function_id": 2},
            {"function_id": 4, "name": "Loop", "hierarchy_level": 4, "manager_function_id": 4},
        ])
        projects = pd.DataFrame({"function_id": [1, 2, 3, 4, None, 99] * 100})
        employees = pd.DataFrame([{"function_id": 3, "firstname": "Ada", "lastname": "Lovelace"}])
        with patch("app.presentation.components.planning_catalog._build_function_lookup",
                          wraps=_build_function_lookup) as build:
            result = enrich_projects_with_organization(projects, functions, employees)
        build.assert_called_once()
        self.assertEqual(result["level_3_manager_name"].tolist()[:6], ["—", "Service", "Service", "—", "—", "—"])
        self.assertEqual(result["project_manager"].iloc[2], "Ada Lovelace")
        self.assertEqual(result["project_manager"].iloc[1], "Service")
