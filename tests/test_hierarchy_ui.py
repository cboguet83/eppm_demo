"""Hierarchy catalog Settings and optional selections in all six entity dialogs."""

from streamlit.testing.v1 import AppTest
import pytest
from unittest.mock import patch

from app.domain.organization.models import Team
from app.infrastructure.database.schema_init import init_db
from app.operator_services import create_organization_service, create_resource_pool_service
from tests.test_layered_organization_ui import dialog as team_dialog
from tests.test_layered_resource_pool_ui import dialog as pool_dialog


@pytest.fixture
def database(tmp_path):
    path = str(tmp_path / "hierarchy-ui.db")
    init_db(path)
    return path


@pytest.mark.parametrize("kind", ["team", "pool", "group"])
def test_create_edit_and_clear_optional_hierarchy_in_entity_dialogs(database, kind):
    organization = create_organization_service(database)
    resources = create_resource_pool_service(database)
    launcher, add, edit, read, identity = {
        "team": (team_dialog, "_open_add_team_dialog(service, functions)",
                 "_open_edit_team_dialog(service, {id}, functions)", organization.get_all_teams, "team_id"),
        "pool": (pool_dialog, "_open_add_pool_dialog(service)",
                 "_open_edit_pool_dialog(service, {id})", resources.get_all_pools, "id"),
        "group": (pool_dialog, "_open_add_pool_group_dialog(service)",
                  "_open_edit_pool_group_dialog(service, {id})", resources.get_all_pool_groups, "id"),
    }[kind]
    app = launcher(database, add)
    selector = app.selectbox(key="hierarchy_type_selection")
    assert selector.value == 0
    assert selector.options == ["None", "ressort", "service", "division", "equipe", "region", "brigade", "district"]
    app.text_input[0].input("Classified")
    selector.set_value(4)
    app.button[0].click().run()
    assert not app.exception
    entity = read()[0]
    assert entity.hierarchy_type_id == 4
    app = launcher(database, edit.format(id=getattr(entity, identity)))
    assert app.selectbox(key="hierarchy_type_selection").value == 4
    app.selectbox(key="hierarchy_type_selection").set_value(2)
    app.button[0].click().run()
    assert not app.exception and read()[0].hierarchy_type_id == 2
    app.selectbox(key="hierarchy_type_selection").set_value(0)
    app.button[0].click().run()
    assert not app.exception and read()[0].hierarchy_type_id is None


def settings_screen(path):
    from app.operator_services import create_settings_workspace
    from app.presentation.pages.settings import render_settings_view
    from app.presentation.i18n import set_current_locale
    set_current_locale("en")
    render_settings_view(create_settings_workspace(path))


def test_settings_catalog_creates_localized_labels_edits_and_deletes(database):
    app = AppTest.from_function(settings_screen, args=(database,), default_timeout=15)
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
    service = create_organization_service(database)
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


def test_settings_cannot_delete_a_type_assigned_to_a_team(database):
    service = create_organization_service(database)
    service.create_team(Team("Existing", hierarchy_type_id=1))
    app = AppTest.from_function(settings_screen, args=(database,), default_timeout=15)
    app.session_state["settings_tab_selection"] = "Hierarchy types"
    app.run()
    app.selectbox(key="hierarchy_catalog_selection").set_value(1).run()
    app.checkbox[0].check().run()
    app.button[1].click().run()
    assert not app.exception and app.error
    assert service.get_all_teams()[0].hierarchy_type_id == 1


def team_screen(path):
    from app.operator_services import create_organization_service
    from app.presentation.pages.organization import render_teams
    from app.presentation.i18n import set_current_locale
    set_current_locale("en")
    render_teams(create_organization_service(path))


def test_team_table_includes_shared_hierarchy_labels_and_empty_assignments(database):
    service = create_organization_service(database)
    service.create_team(Team("Assigned", hierarchy_type_id=4))
    service.create_team(Team("Unassigned"))
    with patch("app.presentation.pages.organization._table", return_value=None) as table:
        app = AppTest.from_function(team_screen, args=(database,)).run()
    assert not app.exception
    assert [row["hierarchy_type"] for row in table.call_args.kwargs["teams"]] == ["equipe", ""]
