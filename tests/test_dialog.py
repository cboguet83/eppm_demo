"""Storage-independent popup completion and shared-wrapper conventions."""

import pytest
from streamlit.testing.v1 import AppTest


def dialog_screen(mode):
    import streamlit as st
    from app.presentation.components.dialog import dialog

    @dialog("Complete popup")
    def content():
        st.text_input("First field")
        if mode == "return":
            st.info("Nothing more to load")
            return
        if mode == "stop":
            st.error("Access denied")
            st.stop()
        st.button("Last action")

    content()


@pytest.mark.parametrize("mode", ["normal", "return", "stop"])
def test_completion_is_emitted_after_content_including_early_exit(mode):
    app = AppTest.from_function(dialog_screen, args=(mode,)).run()
    assert not app.exception
    modal = app.get("dialog")[0]
    elements = list(modal)
    readiness = [element for element in elements if element.type == "bidi_component"]
    assert len(readiness) == (0 if mode == "stop" else 1)
    if readiness:
        assert readiness[0].key == "eppm_dialog_ready"
    assert app.text_input[0].label == "First field"
    if mode == "stop":
        assert app.error[0].value == "Access denied"


def test_all_native_popup_modules_use_shared_completion():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "presentation"
    dialogs = 0
    for path in root.rglob("*.py"):
        if path.name == "dialog.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert not (isinstance(node.func.value, ast.Name)
                            and node.func.value.id == "st" and node.func.attr == "dialog"), path
            if isinstance(node, ast.FunctionDef):
                dialogs += sum(isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
                               and item.func.id == "dialog" for item in node.decorator_list)
    assert dialogs == 51
