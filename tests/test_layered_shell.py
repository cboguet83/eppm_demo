"""Storage-independent Streamlit routing and launcher contracts."""

import os
from pathlib import Path
import subprocess
import sys

import pytest
from streamlit.testing.v1 import AppTest

from app.presentation.navigation import PAGE_PLANNING, PAGE_PORTFOLIO, PAGE_SETTINGS


def shell_app() -> None:
    """Exercise shell routing with injected page renderers and totals."""
    from functools import partial
    import streamlit as st
    from app.presentation.components.application_workspace import ApplicationWorkspace
    from app.presentation.navigation import PAGE_PLANNING, PAGE_PORTFOLIO, PAGE_SETTINGS
    from app.presentation.shell import render_application

    st.session_state["shell_runs"] = st.session_state.get("shell_runs", 0) + 1

    def totals():
        st.session_state["totals_reads"] = st.session_state.get("totals_reads", 0) + 1
        return {"projects": 1, "tasks": 2, "dependencies": 0, "pools": 3}

    render_application(
        ApplicationWorkspace(
            'shell-routing-test',
            {
                page: partial(st.write, page)
                for page in (PAGE_PLANNING, PAGE_PORTFOLIO, PAGE_SETTINGS)
            },
            totals,
        )
    )



def test_shell_routes_navigation_redirects_and_language_changes():
    from tests.test_fragment_reruns import FragmentRun

    app = AppTest.from_function(shell_app)
    rerun = FragmentRun("app_sidebar_nav", widget_index=2, full_app_request=True)
    rerun.run(app)
    assert not app.exception
    assert PAGE_SETTINGS in [item.value for item in app.markdown]
    assert PAGE_PORTFOLIO not in [item.value for item in app.markdown]
    assert app.session_state["shell_runs"] == 2
    assert app.session_state["totals_reads"] == 2
    deltas = [message for message in rerun.messages if message.WhichOneof("type") == "delta"]
    assert deltas and any(message.metadata.delta_path[0] == 1 for message in deltas)
    assert app.radio(key="app_sidebar_nav").value == "settings:org_structure"
    app.session_state["nav_redirect"] = PAGE_PLANNING
    app.run()
    assert app.radio(key="app_sidebar_nav").value == PAGE_PLANNING
    assert app.session_state["shell_runs"] == 3
    assert app.session_state["totals_reads"] == 3
    app.selectbox(key="app_language_selector").set_value("fr").run()
    assert not app.exception
    assert app.selectbox(key="app_language_selector").value == "fr"
    app.session_state["nav_redirect"] = "obsolete route"
    app.run()
    assert PAGE_PORTFOLIO in [item.value for item in app.markdown]


def test_sidebar_starts_with_language_title_and_plain_navigation():
    """Keep global language choice above the undecorated application menu."""
    app = AppTest.from_function(shell_app).run()
    assert not app.exception
    assert app.sidebar.title[0].value == "EPPM POC"
    assert app.radio(key="app_sidebar_nav").options == [
        "Portfolio Overview", "Planning & Milestones", "Settings",
    ]
    elements = [element.type for element in app.sidebar]
    assert elements.index("selectbox") < elements.index("title") < elements.index("radio")


def test_sidebar_places_settings_after_finance():
    """Keep Settings immediately after Finance when both pages are available."""
    def app_with_finance():
        import streamlit as st
        from app.presentation.components.application_workspace import ApplicationWorkspace
        from app.presentation.navigation import PAGE_FINANCE, PAGE_SETTINGS
        from app.presentation.shell import render_application

        render_application(ApplicationWorkspace(
            'sidebar-finance-order',
            {PAGE_SETTINGS: lambda: st.write('Settings'),
             PAGE_FINANCE: lambda: st.write('Finance')},
            totals=None,
        ))

    app = AppTest.from_function(app_with_finance).run()
    assert not app.exception
    assert app.radio(key="app_sidebar_nav").options == ["Finance", "Settings"]


def test_settings_subsections_are_hidden_until_settings_opens():
    """Settings reveals its sections and resets to Organization on reentry."""
    app = AppTest.from_function(shell_app).run()
    assert not any(radio.key == "rb_settings_section" for radio in app.radio)
    app.radio(key="app_sidebar_nav").set_value(PAGE_SETTINGS).run()
    menu = app.sidebar.radio(key="app_sidebar_nav")
    assert menu.value == "settings:org_structure"
    assert [label.strip() for label in menu.options][-5:] == [
        "Settings", "Organization Structure", "Parameter Definition", "Project configuration", "Tag Management",
    ]
    assert len(app.sidebar.radio) == 1
    menu.set_value("settings:param_def").run()
    assert app.session_state["rb_settings_section"] == "param_def"
    assert PAGE_SETTINGS in [item.value for item in app.markdown]
    app.radio(key="app_sidebar_nav").set_value("settings:tag_management").run()
    assert app.session_state["rb_settings_section"] == "tag_management"
    assert PAGE_SETTINGS in [item.value for item in app.markdown]
    app.radio(key="app_sidebar_nav").set_value(PAGE_PORTFOLIO).run()
    assert len(app.radio(key="app_sidebar_nav").options) == 3
    app.radio(key="app_sidebar_nav").set_value(PAGE_SETTINGS).run()
    assert app.sidebar.radio(key="app_sidebar_nav").value == "settings:org_structure"
    assert not app.exception


def test_organization_tabs_follow_catalog_setup_order():
    """Render the first catalog lazily with the requested organization tab order."""
    def settings_app():
        from types import SimpleNamespace
        from unittest.mock import patch
        import streamlit as st
        from app.presentation.pages.settings import render_settings_view

        with patch("app.presentation.pages.settings.render_function_types",
                   side_effect=lambda service: st.write("Function types loaded")):
            render_settings_view(SimpleNamespace(organization=None))

    app = AppTest.from_function(settings_app, default_timeout=15).run()
    assert not app.exception
    assert [tab.label.split(" ", 1)[-1] if tab.label[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" else tab.label
            for tab in app.tabs] == [
        "Function Types", "Hierarchy types", "Functions", "Teams", "Employees", "Pool Types", "Resource Pools",
    ]
    assert "Function types loaded" in [item.value for item in app.markdown]
    assert not app.radio
    assert not app.header


def test_tag_management_has_four_lazy_tabs():
    """Each tag tab loads its own renderer without organization services."""
    def tags_app():
        from contextlib import ExitStack
        from types import SimpleNamespace
        from unittest.mock import patch
        import streamlit as st
        from app.presentation.pages.settings import render_settings_view

        st.session_state["rb_settings_section"] = "tag_management"
        with ExitStack() as stack:
            for name in ("tag_groups", "tag_dictionary", "project_tags", "task_tags"):
                stack.enter_context(patch(
                    "app.presentation.pages.settings.render_" + name,
                    side_effect=lambda service, name=name: st.write(name),
                ))
            render_settings_view(SimpleNamespace(tags=None))

    app = AppTest.from_function(tags_app).run()
    assert [tab.label for tab in app.tabs] == [
        "Tag Groups", "Tag Dictionary", "Project Tags", "Task Tags",
    ]
    for label, renderer in zip(
        [tab.label for tab in app.tabs],
        ("tag_groups", "tag_dictionary", "project_tags", "task_tags"),
        strict=True,
    ):
        app.session_state["tag_management_tab"] = label
        app.run()
        assert not app.exception
        assert [item.value for item in app.markdown] == [renderer]
        assert not app.header


def test_navigation_replaces_the_outgoing_page_container_and_its_controls():
    """Keep stale dashboard controls out of the next page during fragment routing."""
    from tests.test_fragment_reruns import FragmentRun

    def app_with_issue_button():
        import streamlit as st
        from app.presentation.components.application_workspace import ApplicationWorkspace
        from app.presentation.navigation import PAGE_DASHBOARD, PAGE_SETTINGS
        from app.presentation.shell import render_application

        @st.fragment
        def dashboard():
            st.button("Active Issues", key="dashboard_issue_count")

        render_application(ApplicationWorkspace("navigation-test", {
            PAGE_DASHBOARD: dashboard,
            PAGE_SETTINGS: lambda: st.write("Settings content"),
        }, None))

    app = AppTest.from_function(app_with_issue_button)
    rerun = FragmentRun("app_sidebar_nav", widget_index=1, full_app_request=True)
    rerun.run(app)
    assert not app.exception
    assert not app.button
    assert "Settings content" in [element.value for element in app.markdown]
    blocks = [message.delta.add_block for message in rerun.messages
              if message.WhichOneof("type") == "delta" and message.delta.HasField("add_block")]
    assert any(block.id.endswith(f"-application_page_{PAGE_SETTINGS}") for block in blocks)



def test_retained_page_rejects_a_route_outside_the_authorized_workspace():
    def unavailable_page_app():
        import streamlit as st
        from app.presentation.components.application_workspace import ApplicationWorkspace
        from app.presentation.shell import _render_application_page

        st.session_state["app_sidebar_nav"] = "unavailable"
        _render_application_page(ApplicationWorkspace("unused", {"allowed": lambda: st.write("protected")}, None))

    app = AppTest.from_function(unavailable_page_app).run()
    assert not app.exception
    assert "no assigned application access" in app.info[0].value
    assert not app.markdown



@pytest.mark.parametrize("project_id,task_id", [("42", "7"), ("bad", "-2"), ("0", "")])
def test_planning_deep_links_validate_ids_and_consume_query_parameters(
    project_id, task_id
):
    app = AppTest.from_function(shell_app)
    app.query_params.update(nav="planning", project_id=project_id, task_id=task_id)
    app.run()
    assert not app.exception
    assert app.radio(key="app_sidebar_nav").value == PAGE_PLANNING
    assert not app.query_params
    if project_id == "42":
        assert app.session_state["target_planning_project_id"] == 42
        assert app.session_state["ms_multi_projects"] == [42]
        assert app.session_state["target_planning_task_id"] == 7
    else:
        assert "target_planning_project_id" not in app.session_state
        assert "target_planning_task_id" not in app.session_state



@pytest.mark.parametrize("argv", [["--help"], ["-h"]])
def test_launcher_help_does_not_initialize_a_database(argv):
    result = subprocess.run(
        [sys.executable, "streamlit_app.py", *argv],
        env={**os.environ, "DATABASE_URL": "unconfigured", "DATABASE_OPERATOR_URL": "unconfigured"},
        capture_output=True, text=True, check=False, timeout=30,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 0, result.stderr
    assert "--force-reseed" in result.stdout and "--projects" in result.stdout


@pytest.mark.parametrize("flag", ["--force", "-f", "--seed-projects", "-n"])
def test_retired_startup_flags_fail_without_initializing_storage(flag):
    result = subprocess.run(
        [sys.executable, "-m", "app.main", flag],
        env={**os.environ, "DATABASE_URL": "unconfigured", "DATABASE_OPERATOR_URL": "unconfigured"},
        capture_output=True, text=True, check=False, timeout=30,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def test_streamlit_main_ignores_operator_arguments_and_gates_unconfigured_business_access(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("DATABASE_URL", "unconfigured")
    monkeypatch.setattr(sys, "argv", ["streamlit_app.py", "--force-reseed", "--projects", "2"])
    monkeypatch.setattr("app.operator_services.create_maintenance_service",
                        lambda *args, **kwargs: pytest.fail("UI execution must not invoke maintenance."))

    def main_app():
        from app.main import main
        main()

    app = AppTest.from_function(main_app).run()
    assert not app.exception and app.error
    assert not app.radio and not app.dataframe and not app.metric


def test_settings_only_access_opens_the_organization_child():
    """The only authorized parent page must still expose selectable children."""
    def settings_only_app():
        import streamlit as st
        from app.presentation.components.application_workspace import ApplicationWorkspace
        from app.presentation.navigation import PAGE_SETTINGS
        from app.presentation.shell import render_application

        render_application(ApplicationWorkspace(
            "settings-only", {PAGE_SETTINGS: lambda: st.write("Settings content")}, None,
        ))

    app = AppTest.from_function(settings_only_app).run()
    assert not app.exception
    assert app.radio(key="app_sidebar_nav").value == "settings:org_structure"
    assert len(app.radio(key="app_sidebar_nav").options) == 5
