"""Planning display projections handle incomplete references without inventing owners."""

from types import SimpleNamespace

import pandas as pd
import pytest

from app.application.ports.references import PoolGroupReference, PoolHierarchyMember
from app.presentation.components.planning_catalog import (
    enrich_projects_with_organization, get_function_occupant_names,
)
from app.presentation.pages.planning import _build_resource_pool_hierarchy


def test_function_labels_ignore_unresolved_employees_and_keep_the_first_valid_occupant() -> None:
    functions = pd.DataFrame([
        {"function_id": 10, "name": "Manager", "manager_function_id": None},
        {"function_id": 20, "name": "Vacant", "manager_function_id": 10},
        {"function_id": None, "name": "No identity"},
        {"function_id": "invalid", "name": "Invalid identity"},
    ])
    employees = pd.DataFrame([
        {"function_id": None, "firstname": "Unassigned"},
        {"function_id": "invalid", "firstname": "Invalid reference"},
        {"function_id": 999, "firstname": "Unrelated"},
        {"function_id": 10, "firstname": "First", "lastname": "Occupant"},
        {"function_id": 10, "firstname": "Second", "lastname": "Occupant"},
    ]).fillna({"firstname": "", "lastname": ""})
    assert get_function_occupant_names(functions, employees) == {10: "First Occupant", 20: "Vacant"}
    project = pd.DataFrame([{"id": 1, "function_id": 20}])
    enriched = enrich_projects_with_organization(project, functions, employees)
    assert enriched.iloc[0].project_manager == "Vacant"
    assert "level_3_manager_name" not in enriched and "level_3_manager_id" not in enriched
    assert project.columns.tolist() == ["id", "function_id"]


@pytest.mark.parametrize("employees", [None, pd.DataFrame(), pd.DataFrame([{"firstname": "No function column"}])])
def test_function_names_remain_available_when_employee_references_are_absent(employees) -> None:
    functions = pd.DataFrame([{"function_id": 10, "name": "Vacant manager"}])
    assert get_function_occupant_names(functions, employees) == {10: "Vacant manager"}




def test_resource_hierarchy_bounds_cycles_and_omits_missing_pool_references() -> None:
    # Synthetic read projections exercise the renderer's defensive cycle guard;
    # real database cycle prevention is tested independently in resource tests.
    groups = [PoolGroupReference(1, "First"), PoolGroupReference(2, "Second")]
    members = [
        PoolHierarchyMember(1, child_group_id=2), PoolHierarchyMember(2, child_group_id=1),
        PoolHierarchyMember(1, pool_id=10), PoolHierarchyMember(2, pool_id=999),
    ]
    workspace = SimpleNamespace(resources=SimpleNamespace(group_choices=lambda: groups, group_membership=lambda: members))
    hierarchy = _build_resource_pool_hierarchy(workspace, [{"id": 10, "name": "Available pool"}])
    assert len(hierarchy) == 2
    assert all(node["descendant_pool_ids"] == [10] for node in hierarchy)
    pending = list(hierarchy)
    nodes = []
    while pending:
        node = pending.pop()
        nodes.append(node)
        assert len(nodes) <= 8
        pending.extend(node.get("children", []))
    cycles = [node for node in nodes if node.get("cycle_blocked")]
    assert len(cycles) == 2
    assert all(node["children"] == [] and node["descendant_pool_ids"] == [] for node in cycles)
    assert {node["pool_id"] for node in nodes if node["node_type"] == "pool"} == {10}
