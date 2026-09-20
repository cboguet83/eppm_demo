"""Storage-independent WBS validation and project-save test helper."""

import pytest

from app.domain.projects.wbs import normalize_allocations, normalize_wbs


def save_allocation(service, project_id, allocations, **overrides):
    project = service.get_project_by_id(project_id)
    arguments = dict(project_id=project_id, name=project.name, status=project.status,
                     strategic_priority_id=project.strategic_priority_id,
                     dynamic_attributes=project.dynamic_attributes, wbs_allocations=allocations)
    return service.update_project(**(arguments | overrides))


@pytest.mark.parametrize("code", ["WBS.01-A_2", "#TEMP-1", "abc", "ABC", "123", "_", "a" * 128])
def test_wbs_codes_keep_case_and_optional_fictive_prefix(code):
    assert normalize_wbs(" " + code + " ", " Description ") == (code, "Description")


@pytest.mark.parametrize("code", ["", "#", "##TEMP", "A B", "A/B", "A#B", "é", "a" * 129, None, 42])
def test_wbs_codes_reject_invalid_characters_and_empty_identifiers(code):
    with pytest.raises(ValueError):
        normalize_wbs(code, "")


@pytest.mark.parametrize("value", [-1, 101, 1.5, 100.0, True, "50", None])
def test_percentages_are_validated_without_rounding(value):
    with pytest.raises(ValueError, match="whole percentage"):
        normalize_allocations([{"wbs_id": 1, "percentage": value}])


@pytest.mark.parametrize("raw", [None, {}, [None], [{"wbs_id": 1}], [{"wbs_id": True, "percentage": 0}],
                                [{"wbs_id": 0, "percentage": 0}], [{"wbs_id": 2**63, "percentage": 0}],
                                [{"wbs_id": 1, "percentage": 0}] * 2])
def test_malformed_and_duplicate_assignments_are_rejected(raw):
    with pytest.raises(ValueError):
        normalize_allocations(raw)
