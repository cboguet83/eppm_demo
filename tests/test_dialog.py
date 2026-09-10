"""Shared popup completion and current project permission-read boundaries."""

from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.application.services.projects import ProjectService
from tests.test_business_transaction_security import business as business
from tests.test_fragment_reruns import FragmentRun
from tests.test_project_dialog_performance import project_screen


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


@pytest.mark.parametrize("operation,key", [
    ("create", "portfolio_create_manager_3"),
    ("edit", "portfolio_edit_manager_1"),
])
def test_permission_read_is_shared_within_render_but_fresh_on_fragment_interaction(business, operation, key):
    path, _, _, _, manager = business
    app = AppTest.from_function(project_screen, args=(path, manager.actor, operation))
    reads = []
    before = []
    original = ProjectService.permissions

    def permissions(service):
        reads.append(service)
        return original(service)

    rerun = FragmentRun(key, lambda: before.append(len(reads)))
    with patch.object(ProjectService, "permissions", permissions):
        rerun.run(app)
    # Creation also checks before preparing references. Editing reads the project
    # through its separately authorized service before entering the dialog.
    assert before == [2 if operation == "create" else 1]
    assert len(reads) == before[0] + 1
    rerun.assert_isolated()


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
    assert dialogs == 40


def cancellation_screen(path, operation):
    import pandas as pd
    import streamlit as st
    from app.operator_services import (
        create_organization_service, create_resource_pool_service, create_tag_service,
    )
    from app.presentation.components import organization_dialogs as org
    from app.presentation.components import resource_pool_dialogs as pools
    from app.presentation.components import tag_dialogs as tags
    from app.presentation.i18n import set_current_locale

    set_current_locale("en")
    organization = create_organization_service(path)
    resources = create_resource_pool_service(path)
    tag_service = create_tag_service(path)
    empty = pd.DataFrame()
    actions = {
        "function": (org._open_add_function_dialog, (organization, empty, empty)),
        "team": (org._open_add_team_dialog, (organization, empty)),
        "function_type": (org._open_add_function_type_dialog, (organization,)),
        "employee": (org._open_add_employee_dialog, (organization, empty)),
        "pool": (pools._open_add_pool_dialog, (resources,)),
        "pool_group": (pools._open_add_pool_group_dialog, (resources,)),
        "tag": (tags._open_add_tag_dialog, (tag_service, empty)),
        "tag_group": (tags._open_add_tag_group_dialog, (tag_service,)),
        "mapping": (pools._open_add_pool_mapping_dialog, (
            resources, 1, pd.DataFrame([{"team_id": 999, "team_name": "Stale choice"}]), empty,
        )),
    }
    if st.session_state.pop("test_open_popup", False):
        render, arguments = actions[operation]
        render(*arguments)


@pytest.mark.parametrize("operation", [
    "function", "team", "function_type", "employee", "pool", "pool_group", "tag", "tag_group", "mapping",
])
def test_cancel_closes_native_creation_popup_without_writing_or_leaving_readiness_elements(business, operation):
    from contextlib import closing
    from hashlib import sha256
    from app.infrastructure.database.connection import get_db

    path, *_ = business

    def fingerprint():
        with closing(get_db(path)) as connection:
            return sha256("\n".join(connection.iterdump()).encode()).hexdigest()

    before = fingerprint()
    app = AppTest.from_function(cancellation_screen, args=(path, operation))
    app.session_state["test_open_popup"] = True
    # Dispatch the retained dialog fragment, as the browser does. AppTest.run()
    # alone would close this conditional popup without executing its Cancel code.
    rerun = FragmentRun("cancel", widget_trigger=True, widget_label="Cancel")
    rerun.run(app)
    assert not app.exception and not app.get("dialog")
    assert not app.get("bidi_component")
    assert fingerprint() == before
