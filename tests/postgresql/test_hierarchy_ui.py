"""Hierarchy catalog Settings and optional selections in all six entity dialogs."""

from streamlit.testing.v1 import AppTest
import psycopg
import pytest
from unittest.mock import patch

from app.domain.organization.models import Team
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.main import create_organization_service, create_resource_pool_service
from app.runtime import RuntimeResources


def test_unassigned_hierarchy_label_uses_the_originating_session_locale():
    """AppTest serializes values outside the script's language context."""
    from app.presentation.i18n import get_current_locale, set_current_locale

    previous = get_current_locale()
    try:
        set_current_locale("fr")
        app = AppTest.from_string('''
import streamlit as st
from app.presentation.i18n import set_current_locale
from app.presentation.components.hierarchy import hierarchy_type_selector
set_current_locale("en")
value = hierarchy_type_selector([])
if st.button("Save"):
    st.write("unassigned" if value is None else "assigned")
''').run()
        assert app.selectbox[0].options == ["None"]
        app.button[0].click().run()
        assert not app.exception
        assert app.markdown[0].value == "unassigned"
    finally:
        set_current_locale(previous)


@pytest.fixture
def database(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        ensure_reference_catalog(connection)
    return RuntimeResources(authorized.database, authorized.key)


@pytest.fixture
def access(authorized):
    return authorized.binding(4).access


def entity_screen(service, kind, identity):
    """Render the actual modal with a native service across AppTest reruns."""
    from app.presentation.components import organization_dialogs, resource_pool_dialogs
    from app.presentation.components.organization_frames import functions_frame
    from app.presentation.i18n import set_current_locale

    set_current_locale('en')
    if kind == 'team':
        functions = functions_frame(service.get_all_functions())
        if identity is None:
            organization_dialogs._open_add_team_dialog(service, functions)
        else:
            organization_dialogs._open_edit_team_dialog(service, identity, functions)
    elif kind == 'pool':
        if identity is None:
            resource_pool_dialogs._open_add_pool_dialog(service)
        else:
            resource_pool_dialogs._open_edit_pool_dialog(service, identity)
    elif identity is None:
        resource_pool_dialogs._open_add_pool_group_dialog(service)
    else:
        resource_pool_dialogs._open_edit_pool_group_dialog(service, identity)


@pytest.mark.parametrize("kind", ["team", "pool", "group"])
def test_create_edit_and_clear_optional_hierarchy_in_entity_dialogs(database, access, kind):
    organization = create_organization_service(database, access=access)
    resources = create_resource_pool_service(database, access=access)
    service, read, identity = {
        "team": (organization, organization.get_all_teams, "team_id"),
        "pool": (resources, resources.get_all_pools, "id"),
        "group": (resources, resources.get_all_pool_groups, "id"),
    }[kind]
    app = AppTest.from_function(entity_screen, args=(service, kind, None), default_timeout=15).run()
    assert not app.exception
    selector = app.selectbox(key="hierarchy_type_selection")
    assert selector.value == 0
    assert selector.options == ["None", "ressort", "service", "division", "equipe", "region", "brigade", "district"]
    app.text_input[0].input("Classified")
    selector.set_value(4)
    app.button[0].click().run()
    assert not app.exception
    entity = read()[0]
    assert entity.hierarchy_type_id == 4
    app = AppTest.from_function(entity_screen, args=(service, kind, getattr(entity, identity)), default_timeout=15).run()
    assert app.selectbox(key="hierarchy_type_selection").value == 4
    app.selectbox(key="hierarchy_type_selection").set_value(2)
    app.button[0].click().run()
    assert not app.exception and read()[0].hierarchy_type_id == 2
    app.selectbox(key="hierarchy_type_selection").set_value(0)
    app.button[0].click().run()
    assert not app.exception and read()[0].hierarchy_type_id is None


def settings_screen(resources, access):
    from app.main import create_settings_workspace
    from app.presentation.pages.settings import render_settings_view
    from app.presentation.i18n import set_current_locale
    set_current_locale("en")
    render_settings_view(create_settings_workspace(resources, access=access))


def test_settings_catalog_creates_localized_labels_edits_and_deletes(database, access):
    app = AppTest.from_function(settings_screen, args=(database, access), default_timeout=15)
    app.session_state["settings_tab_selection"] = "Hierarchy types"
    app.run()
    assert not app.exception
    app.button[0].click().run()
    assert app.error
    app.text_input[0].input("custom")
    app.text_input[1].input("Custom label")
    app.text_input[2].input("Libellé personnalisé")
    app.button[0].click().run()
    assert not app.exception
    service = create_organization_service(database, access=access)
    saved = service.get_all_hierarchy_types()[-1]
    assert saved.code == "custom" and saved.label("fr") == "Libellé personnalisé"
    app.selectbox(key="hierarchy_catalog_selection").set_value(saved.id).run()
    assert app.text_input[0].disabled
    app.text_input[1].input("Renamed label")
    app.button[0].click().run()
    assert service.get_all_hierarchy_types()[-1].label("en") == "Renamed label"
    assert app.button[1].disabled
    app.checkbox[0].check().run()
    app.button[1].click().run()
    assert not app.exception
    assert len(service.get_all_hierarchy_types()) == 7


def test_settings_cannot_delete_a_type_assigned_to_a_team(database, access):
    service = create_organization_service(database, access=access)
    service.create_team(Team("Existing", hierarchy_type_id=1))
    app = AppTest.from_function(settings_screen, args=(database, access), default_timeout=15)
    app.session_state["settings_tab_selection"] = "Hierarchy types"
    app.run()
    app.selectbox(key="hierarchy_catalog_selection").set_value(1).run()
    app.checkbox[0].check().run()
    app.button[1].click().run()
    assert not app.exception and app.error
    assert service.get_all_teams()[0].hierarchy_type_id == 1


def team_screen(resources, access):
    from app.main import create_organization_service
    from app.presentation.pages.organization import render_teams
    from app.presentation.i18n import set_current_locale
    set_current_locale("en")
    render_teams(create_organization_service(resources, access=access))


def test_team_table_includes_shared_hierarchy_labels_and_empty_assignments(database, access):
    service = create_organization_service(database, access=access)
    service.create_team(Team("Assigned", hierarchy_type_id=4))
    service.create_team(Team("Unassigned"))
    with patch("app.presentation.pages.organization._table", return_value=None) as table:
        app = AppTest.from_function(team_screen, args=(database, access)).run()
    assert not app.exception
    assert [row["hierarchy_type"] for row in table.call_args.kwargs["teams"]] == ["equipe", ""]
