"""Storage-independent CSV transport boundary validation."""

import pytest

from app.presentation.components.csv_upload import MAX_CSV_BYTES, validated_csv_upload


@pytest.mark.parametrize("payload", [
    "forged", {"error": "size"}, {"error": "encoding"}, {"content": 42, "name": "data.csv"},
    {"content": "data", "name": "not-csv.exe"}, {"content": "\x00", "name": "data.csv"},
    {"content": "x" * (MAX_CSV_BYTES + 1), "name": "data.csv"},
    {"content": "\u20ac" * (MAX_CSV_BYTES // 2), "name": "data.csv"},
    {"content": "\ud800", "name": "data.csv"},
    {"content": "data", "name": "x" * 256 + ".csv"},
])
def test_csv_component_rejects_malformed_or_oversized_payloads_on_server(payload):
    with pytest.raises(ValueError):
        validated_csv_upload(payload)


def test_csv_component_accepts_utf8_bom_and_empty_selection():
    assert validated_csv_upload(None) is None
    assert validated_csv_upload({"content": "\ufeffname\nExample", "name": "template.csv"}) == (
        "name\nExample", "template.csv",
    )
