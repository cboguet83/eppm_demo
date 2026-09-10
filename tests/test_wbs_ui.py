"""WBS settings and project popup authorization with real application services."""

import pytest
from streamlit.testing.v1 import AppTest

from app.main import create_project_service
from tests.test_business_transaction_security import business as business
from tests.test_portfolio_project_modal import open_form, submit
from tests.test_project_dialog_performance import project_screen
from tests.test_wbs import catalog, save_allocation
from tests.test_fragment_reruns import FragmentRun


def settings_screen(path, actor, locale):
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_settings_workspace
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.settings import render_settings_view

    set_current_locale(locale)
    render_settings_view(create_settings_workspace(path, access=BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))))


def catalog_screen(path, actor, locale):
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_settings_workspace
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.wbs import render_wbs_catalog

    set_current_locale(locale)
    render_wbs_catalog(create_settings_workspace(path, access=BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))).wbs)


@pytest.mark.parametrize("locale,title", [("en", "WBS"), ("fr", "OTP")])
def test_business_administrator_can_maintain_catalog_from_settings(business, locale, title):
    path, _, _, _, manager = business
    app = AppTest.from_function(settings_screen, args=(path, manager.actor, locale)).run()
    app.radio(key="rb_settings_section").set_value("project_configuration").run()
    app.session_state["project_configuration_tab"] = title
    app.run()
    assert not app.exception
    assert any(section.value == title for section in app.subheader)
    # Exercise CRUD directly in the production fragment: AppTest does not model
    # browser updates to dynamic tab selection across subsequent widget events.
    app = AppTest.from_function(catalog_screen, args=(path, manager.actor, locale)).run()
    app.text_input(key="wbs_catalog_None_code").set_value("UI.01")
    app.text_area(key="wbs_catalog_None_description").set_value("Displayed description")
    app.checkbox(key="wbs_catalog_None_fictive").check()
    app.button[0].click().run()
    assert not app.exception and not app.error
    row = catalog(path, manager).list_catalog()[0]
    assert row["code"] == "#UI.01" and row["description"] == "Displayed description"
    app.checkbox(key=f"wbs_catalog_{row['id']}_fictive").uncheck()
    app.text_input(key=f"wbs_catalog_{row['id']}_code").set_value("REAL.01")
    app.button[0].click().run()
    assert catalog(path, manager).list_catalog()[0]["code"] == "REAL.01"
    app.checkbox(key=f"wbs_catalog_{row['id']}_confirm").check().run()
    app.button[-1].click().run()
    assert not app.exception and catalog(path, manager).list_catalog() == []


def test_project_editor_cannot_maintain_shared_wbs_catalog(business):
    path, _, _, editor, _ = business
    app = AppTest.from_function(settings_screen, args=(path, editor.actor, "en")).run()
    app.radio(key="rb_settings_section").set_value("project_configuration").run()
    app.session_state["project_configuration_tab"] = "WBS"
    app.run()
    assert not app.exception
    assert any("business administrator" in message.value for message in app.info)
    assert not app.text_input


def test_project_popup_saves_and_removes_wbs_and_rechecks_availability(business):
    path, _, _, editor, manager = business
    identity = catalog(path, manager).save("SHARED", "Description")
    app = open_form(path, editor.actor)
    draft = app.session_state["portfolio_project_modal_state"]
    assert draft.form["links_tab"] in draft.form["tabs"] and draft.form["wbs_tab"] == "WBS"
    assert draft.form["wbs_options"][0]["available"] == 100
    save_allocation(create_project_service(path, access=manager), 2, [{"wbs_id": identity, "percentage": 70}])
    submit(app, changes={"name": "Not saved"}, mutate=lambda event: event.update(wbs=[{"wbs_id": identity, "percentage": 100}]))
    assert "only 30%" in app.session_state["portfolio_project_modal_state"].form["error"]
    projects = create_project_service(path, access=editor)
    assert projects.get_project_by_id(1).name == "Visible"
    submit(app, mutate=lambda event: event.update(wbs=[{"wbs_id": identity, "percentage": 30}]))
    assert projects.get_wbs_allocations(1) == [{"wbs_id": identity, "percentage": 30}]
    app = open_form(path, editor.actor)
    assert app.session_state["portfolio_project_modal_state"].form["wbs"][0]["percentage"] == 30
    submit(app, mutate=lambda event: event.update(wbs=[]))
    assert projects.get_wbs_allocations(1) == []


def test_native_project_editor_custom_links_only_appear_on_useful_links_tab(business):
    path, _, _, _, manager = business
    catalog(path, manager).save("NATIVE", "Shown with code")
    app = AppTest.from_function(project_screen, args=(path, manager.actor, "edit")).run()
    assert not app.exception
    assert not any(item.value == "Custom links" for item in app.subheader)
    # Use the locale's actual label rather than schema capitalization.
    from app.presentation.i18n import load_locale_catalog
    app.session_state["portfolio_edit_1_tabs"] = load_locale_catalog("en")["portfolio"]["tab_details_links"]
    app.run()
    assert any(item.value == "Custom links" for item in app.subheader)
    app.session_state["portfolio_edit_1_tabs"] = "WBS"
    app.run()
    assert not app.exception
    assert not any(item.value == "Custom links" for item in app.subheader)
    assert app.dataframe


def wbs_field_screen(path, actor, disabled):
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_project_service
    from app.presentation.components.wbs_editor import render_wbs_editor
    from app.presentation.i18n import set_current_locale

    set_current_locale("en")
    projects = create_project_service(path, access=BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits())))

    @st.fragment
    def fields():
        st.session_state["wbs_result"] = render_wbs_editor(projects.get_wbs_allocations(1), projects.get_wbs_options(1), "wbs_test", disabled=disabled)
    fields()


@pytest.mark.parametrize("assigned,disabled", [(False, False), (False, True), (True, True)])
def test_native_wbs_empty_catalog_and_read_only_assignments(business, assigned, disabled):
    path, _, _, editor, manager = business
    if assigned:
        identity = catalog(path, manager).save("#READ", "Description")
        save_allocation(create_project_service(path, access=editor), 1, [{"wbs_id": identity, "percentage": 35}])
    app = AppTest.from_function(wbs_field_screen, args=(path, editor.actor, disabled)).run()
    assert not app.exception
    if assigned:
        assert app.dataframe[0].value.iloc[0].to_dict() == {"WBS code": "#READ", "Description": "Description", "Allocation (%)": 35}
    else:
        assert app.info


def test_native_wbs_row_edits_remain_integer_and_show_available_percentage(business):
    path, _, _, editor, manager = business
    first = catalog(path, manager).save("A", "First code")
    second = catalog(path, manager).save("B", "")
    projects = create_project_service(path, access=editor)
    save_allocation(projects, 1, [{"wbs_id": first, "percentage": 40}])
    app = AppTest.from_function(wbs_field_screen, args=(path, editor.actor, False))
    run = FragmentRun("wbs_test", widget_json={"edited_rows": {"0": {"percentage": 25}},
                                             "added_rows": [{"code": "B"}, {"code": None}], "deleted_rows": []})
    run.run(app)
    run.assert_isolated()
    result = app.session_state["wbs_result"]
    assert result == [{"wbs_id": first, "percentage": 25}, {"wbs_id": second, "percentage": 100}]
    assert any("Available for this project: 100%" in caption.value for caption in app.caption)
    save_allocation(projects, 1, result)
    assert projects.get_wbs_allocations(1) == result


def test_catalog_error_keeps_the_form_open_and_never_deletes_assigned_wbs(business):
    path, _, _, editor, manager = business
    identity = catalog(path, manager).save("TAKEN")
    save_allocation(create_project_service(path, access=editor), 1, [{"wbs_id": identity, "percentage": 1}])
    app = AppTest.from_function(catalog_screen, args=(path, manager.actor, "en")).run()
    app.text_input(key="wbs_catalog_None_code").set_value("TAKEN")
    app.button[0].click().run()
    assert "already exists" in app.error[0].value
    app.selectbox(key="wbs_catalog_selection").select(identity).run()
    app.checkbox(key=f"wbs_catalog_{identity}_confirm").check().run()
    app.button[-1].click().run()
    assert "assigned to a project" in app.error[0].value
    assert catalog(path, manager).list_catalog()[0]["code"] == "TAKEN"


def test_native_popup_does_not_reapply_added_rows_to_an_already_edited_draft(business):
    path, _, _, _, manager = business
    first = catalog(path, manager).save("FIRST")
    second = catalog(path, manager).save("SECOND")
    save_allocation(create_project_service(path, access=manager), 1, [{"wbs_id": first, "percentage": 50}])
    app = AppTest.from_function(project_screen, args=(path, manager.actor, "edit"))
    app.session_state["portfolio_edit_1_tabs"] = "WBS"
    delta = {"edited_rows": {"0": {"percentage": 25}}, "added_rows": [{"code": "SECOND", "percentage": 100}], "deleted_rows": []}
    FragmentRun("portfolio_edit_1_wbs_1", widget_json=delta).run(app)
    expected = [{"wbs_id": first, "percentage": 25}, {"wbs_id": second, "percentage": 100}]
    assert app.session_state["portfolio_edit_1_assignments"]["wbs"] == expected
    FragmentRun("portfolio_edit_1_wbs_1", widget_json=delta).run(app)
    assert app.session_state["portfolio_edit_1_assignments"]["wbs"] == expected
