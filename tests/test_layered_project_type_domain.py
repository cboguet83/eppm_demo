"""Business-rule regressions that require neither a database nor Streamlit."""

import pytest

from app.domain.projects.project_types import (
    ProjectType, make_applicability, normalize_details, resolve_template,
    validate_deletion, validate_rename,
)
from app.domain.projects.property_values import encode_property_value


def test_required_name_and_general_protection() -> None:
    """Names are normalized while the protected General invariant is retained."""
    assert normalize_details("  Rail  ", "  Description  ") == ("Rail", "Description")
    with pytest.raises(ValueError, match="name is required"):
        normalize_details("  ", "Description")
    general = ProjectType(1, "General", "", True)
    validate_rename(general, "General")
    for requested_name in ("Renamed", "General "):
        with pytest.raises(ValueError, match="cannot be renamed"):
            validate_rename(general, requested_name)
    validate_rename(ProjectType(2, "Rail", "", False), "Road")


@pytest.mark.parametrize("general,projects,exclusive,message", [
    (True, False, False, "General type cannot be deleted"),
    (False, True, False, "Reassign this type's projects"),
    (False, False, True, "exclusive properties"),
])
def test_deletion_preserves_business_references(
    general: bool, projects: bool, exclusive: bool, message: str,
) -> None:
    """Each independent reason for preserving a type rejects its deletion."""
    with pytest.raises(ValueError, match=message):
        validate_deletion(
            ProjectType(1, "Type", "", general),
            has_projects=projects, has_exclusive_properties=exclusive,
        )
    validate_deletion(None, has_projects=False, has_exclusive_properties=False)


def test_applicability_requires_a_selection_and_deduplicates_membership() -> None:
    """Selected scope is nonempty; all-types scope clears selected membership."""
    with pytest.raises(ValueError, match="Select at least one"):
        make_applicability(False, [])
    assert make_applicability(False, [3, 2, 3]).type_ids == (2, 3)
    assert make_applicability(True, [2]).type_ids == ()


def test_template_inheritance_and_explicit_empty_defaults_are_independent() -> None:
    """Resolve selected/global scope, false overrides, and cleared defaults."""
    definitions = [
        dict(param_id=pid, group_id=None, param_name=pid, param_type="TEXT",
             mandatory=True, alias=None, applies_to_all=pid != "hidden")
        for pid in ("inherited", "optional", "null", "empty", "list", "hidden")
    ]
    defaults = {"null": None, "empty": "", "list": ["A"]}
    result = resolve_template(definitions, set(), {"optional": False}, defaults)
    indexed = {row["param_id"]: row for row in result}
    assert "hidden" not in indexed
    assert indexed["inherited"]["mandatory"] is True
    assert indexed["inherited"]["has_default"] is False
    assert indexed["optional"]["mandatory"] is False
    assert indexed["null"]["has_default"] is True
    assert indexed["null"]["default_value"] is None
    assert indexed["empty"]["default_value"] == ""
    indexed["list"]["default_value"].append("B")
    assert defaults["list"] == ["A"]
    assert "has_default" not in definitions[0]
    assert resolve_template(definitions, {"hidden"}, {}, {})[-1]["param_id"] == "hidden"


@pytest.mark.parametrize("kind,value,encoded_kind", [
    ("TEXT", "hello", "text"), ("TEXT", None, "null"), ("TEXT", "", "empty"),
    ("NUMBER", 0, "number"), ("NUMBER", 1.25, "number"),
    ("DATE", "2026-09-08", "date"), ("ENUM", "A", "text"),
    ("MULTI_ENUM", ["B", "A"], "list"), ("MULTI_ENUM", [], "list"),
    ("TAGS", ["free text"], "list"), ("URL", "https://example.org", "text"),
    ("HYPERLINK", "https://example.org/page", "text"),
])
def test_supported_property_values_preserve_their_kind(
    kind: str, value: object, encoded_kind: str,
) -> None:
    """The domain retains typed scalars and ordered selections."""
    encoded = encode_property_value("p", kind, value, {"A", "B"})
    assert encoded[0] == encoded_kind
    if isinstance(value, list):
        assert encoded[4] == value


@pytest.mark.parametrize("kind,value", [
    ("UNKNOWN", "text"), ("NUMBER", True), ("NUMBER", "12"),
    ("NUMBER", float("nan")), ("NUMBER", float("inf")),
    ("TEXT", 12), ("ENUM", "unknown"), ("MULTI_ENUM", "A"),
    ("MULTI_ENUM", [1]), ("MULTI_ENUM", ["A", "A"]),
    ("MULTI_ENUM", ["unknown"]), ("DATE", "20260908"),
    ("DATE", "2026-99-01"),
])
def test_incompatible_property_values_are_rejected(kind: str, value: object) -> None:
    """Validation rejects malformed input before it can become stored truth."""
    with pytest.raises(ValueError):
        encode_property_value("p", kind, value, {"A", "B"})
