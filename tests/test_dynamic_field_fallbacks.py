"""Legacy property values remain inspectable and editable without unsafe navigation."""

from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from app.presentation.pages.portfolio import _property_value_html


def dynamic_field_app(kind: str, value: object, disabled: bool = False) -> None:
    """Exercise the production widget boundary with a legacy property projection."""
    import pandas as pd
    import streamlit as st
    from app.presentation.components.dynamic_fields import render_dynamic_field

    parameter = pd.Series({"param_id": "VALUE", "param_name": "Legacy value", "param_type": kind})
    result = render_dynamic_field(parameter, pd.DataFrame(), value, "legacy", disabled=disabled)
    st.session_state["result"] = result


@pytest.mark.parametrize("kind,value", [("DATE", "invalid-date"), ("NUMBER", "invalid-number"), ("NUMBER", [])])
def test_unparseable_legacy_values_can_be_corrected_without_a_script_error(kind, value):
    app = AppTest.from_function(dynamic_field_app, args=(kind, value)).run()
    assert not app.exception
    if kind == "DATE":
        assert app.date_input[0].value is None and app.session_state["result"] == ""
        app.date_input[0].set_value(date(2026, 9, 9)).run()
        assert app.session_state["result"] == "2026-09-09"
    else:
        assert app.number_input[0].value is None and app.session_state["result"] is None
        app.number_input[0].set_value(42).run()
        assert app.session_state["result"] == 42
    assert not app.exception


def test_native_date_drafts_are_preserved_in_read_only_fields():
    app = AppTest.from_function(dynamic_field_app, args=("DATE", date(2026, 9, 9), True)).run()
    assert not app.exception
    assert app.date_input[0].disabled and app.date_input[0].value == date(2026, 9, 9)
    assert app.session_state["result"] == "2026-09-09"


def test_unknown_legacy_field_types_preserve_text_without_creating_html():
    value = '<script>alert("legacy")</script>'
    app = AppTest.from_function(dynamic_field_app, args=("RETIRED_TYPE", value, True)).run()
    assert not app.exception and not app.get("html")
    assert app.text_input[0].disabled and app.text_input[0].value == value
    assert app.session_state["result"] == value


@pytest.mark.parametrize("kind", ["URL", "HYPERLINK"])
@pytest.mark.parametrize("value", ['javascript:alert("legacy")', '<img src=x onerror="alert(1)">'])
def test_legacy_url_inspection_escapes_invalid_values_without_making_them_links(kind, value):
    import html

    rendered = _property_value_html(value, kind, "Legacy link")
    assert rendered == html.escape(value)
    assert "<a " not in rendered and "<img " not in rendered
