"""Persistence and modal regressions for the project experience improvements."""

from dataclasses import replace
from pathlib import Path
import psycopg
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.domain.organization.models import Employee
from app.application.services.business_access import BusinessAccess
from app.infrastructure.postgresql.migration import migrate
from app.operator_services import create_maintenance_service
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import native_screen, runtime as runtime, access as access
from app.domain.resources.models import PoolAssignment, ResourcePool
from app.main import (
    create_collaboration_service, create_organization_service,
    create_project_service, create_resource_pool_service, create_schema_service,
)
from app.presentation.components.property_labels import property_label


@pytest.fixture
def experience_database(runtime: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture) -> RuntimeResources:
    """Prepare project contact examples using native organization operations."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function(function_id,name) VALUES(1,'Engineer'),(2,'Lead')")
    organization = create_organization_service(runtime, access=access)
    organization.create_employee(Employee("Alice", "Smith", "alice@example.invalid", function_id=1, mobile="+352 621 111 111", landline="+352 27 111 111"))
    organization.create_employee(Employee("Bob", "Jones", "bob@example.invalid", function_id=2, mobile="+352 621 222 222", landline="+352 27 222 222"))
    create_project_service(runtime, access=access).update_project(1, "Project", "Draft", 0, 0, {})
    return runtime


def project_dialog(path: RuntimeResources, access: BusinessAccess, operation: str, locale: str = "en") -> AppTest:
    """Keep a production project dialog mounted during full AppTest reruns."""
    return native_screen(f'''
from app.main import create_project_workspace
from app.presentation.components.project_dialogs import open_create_project_dialog, open_edit_project_dialog
from app.presentation.i18n import set_current_locale
set_current_locale({locale!r})
workspace = create_project_workspace(runtime, access=access)
{operation}
''', path, access).run()


def test_employee_landline_is_normalized_persisted_and_resolved_for_contacts(experience_database: RuntimeResources, access: BusinessAccess) -> None:
    organization = create_organization_service(experience_database, access=access)
    employee = organization.get_employee_by_id(1)
    organization.update_employee(replace(employee, landline="  +352 27 000 999  "))
    assert organization.get_employee_by_id(1).landline == "+352 27 000 999"
    service = create_collaboration_service(experience_database, access=access)
    role = service.save_catalog("role", "Sponsor")
    contact_id = service.save_contact(1, role, 1)
    contact = service.list_contacts(1)[0]
    assert contact["mobile"] == "+352 621 111 111"
    assert contact["landline"] == "+352 27 000 999"
    service.reassign_contact(1, contact_id, 2)
    contact = service.list_contacts(1)[0]
    assert (contact["role_id"], contact["function_id"], contact["person"], contact["landline"]) == (role, 2, "Bob Jones", "+352 27 222 222")
    with pytest.raises(ValueError, match="this project"):
        service.reassign_contact(999, contact_id, 1)
    assert service.list_contacts(1)[0]["function_id"] == 2


def test_clean_default_seeding_populates_every_employee_landline(pg_database, clients, tmp_path: Path) -> None:
    service = create_maintenance_service(
        pg_database.operator_url, backup_directory=tmp_path, archive_tools=clients,
    )
    service.seed_defaults()
    with psycopg.connect(pg_database.operator_url) as connection:
        phones = connection.execute("SELECT mobile,landline FROM eppm.employee").fetchall()
    assert phones and all(mobile and landline for mobile, landline in phones)
    assert len({landline for _, landline in phones}) == len(phones)
    assert len(list(tmp_path.glob("*.dump"))) == 1


def test_native_migration_reentry_preserves_employee_phones_and_translated_aliases(
    experience_database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    organization = create_organization_service(experience_database, access=access)
    before = organization.get_employee_by_id(1)
    schema = create_schema_service(experience_database, access=access)
    schema.create_parameter("p", None, "Name", "TEXT")
    schema.set_alias_translation("p", "fr", "Nom")

    assert migrate(authorized.setup.operator_url) == ()
    assert migrate(authorized.setup.operator_url) == ()

    assert organization.get_employee_by_id(1) == before
    assert schema.get_alias_translations("fr") == {"p": "Nom"}


def test_translated_alias_falls_back_to_default_alias_then_name(experience_database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_schema_service(experience_database, access=access)
    service.create_parameter("p", None, "internal_name", "TEXT", alias="Default alias")
    service.set_alias_translation("p", "fr", "  Libellé traduit  ")
    parameter = {"param_id": "p", "param_name": "internal_name", "alias": "Default alias"}
    assert property_label(parameter, service.get_alias_translations("fr")) == "Libellé traduit"
    assert property_label(parameter, service.get_alias_translations("de")) == "Default alias"
    assert property_label({**parameter, "alias": " "}, {}) == "internal_name"
    service.set_alias_translation("p", "fr", " ")
    assert service.get_alias_translations("fr") == {}
    with pytest.raises(ValueError, match="language code"):
        service.set_alias_translation("p", "invalid_locale", "Wrong")
    with pytest.raises(ValueError, match="Unknown property"):
        service.set_alias_translation("missing", "fr", "Wrong")
    service.set_alias_translation("p", "fr", "Nom")
    assert service.delete_parameter("p")
    assert service.get_alias_translations("fr") == {}


def test_alias_table_enforces_nonblank_values_and_references(
    experience_database: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    service = create_schema_service(experience_database, access=access)
    service.create_parameter("p", None, "Property", "TEXT")
    with psycopg.connect(authorized.setup.operator_url) as connection:
        for values in (("missing", "fr", "Name"), ("p", "fr", " "), ("p", " ", "Name")):
            with pytest.raises(psycopg.IntegrityError), connection.transaction():
                connection.execute("INSERT INTO eppm.schema_parameter_translation VALUES(%s,%s,%s)", values)
        assert connection.execute("SELECT count(*) FROM eppm.schema_parameter_translation").fetchone()[0] == 0


def test_project_creation_uses_property_tabs_and_localized_alias_labels(experience_database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_schema_service(experience_database, access=access)
    group = service.create_group("Custom section", 1)
    service.create_parameter("p", group, "internal_name", "TEXT", alias="Default alias")
    service.set_alias_translation("p", "fr", "Nom traduit")
    app = project_dialog(experience_database, access, "open_create_project_dialog(workspace)", "fr")
    assert not app.exception
    assert "Custom section" in [tab.label for tab in app.tabs]
    preview = create_project_service(experience_database, access=access).generate_project_id()
    assert app.text_input(key=f"portfolio_create_{preview}_p").label == "Nom traduit"
    assert not app.expander


def test_project_delete_requires_confirmation_and_cancel_preserves_project(experience_database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_project_service(experience_database, access=access)
    app = project_dialog(experience_database, access, "open_edit_project_dialog(1, workspace)")
    app.button(key="portfolio_delete_project_1").click().run()
    assert not app.exception and service.exists(1)
    assert app.button(key="confirm_delete_project_1")
    app.button(key="cancel_delete_project_1").click().run()
    assert not app.exception and service.exists(1)
    app.button(key="portfolio_delete_project_1").click().run()
    app.button(key="confirm_delete_project_1").click().run()
    assert not app.exception and not service.exists(1)


@pytest.mark.parametrize("event", [{"id": 999, "action": "remove"}, {"id": True, "action": "remove"}, {"id": 1, "action": "unexpected"}, None])
def test_row_action_boundary_rejects_unknown_ids_and_actions(event: object) -> None:
    from app.presentation.components.action_table import action_table

    with patch("streamlit.components.v2.component", return_value=lambda **kwargs: SimpleNamespace(action=event)):
        assert action_table([{"id": 1}], [("id", "ID")], {"remove": "Remove"}, key="safe") is None


def test_unassignment_confirmation_and_cancel_preserve_pool_membership(experience_database: RuntimeResources, access: BusinessAccess) -> None:
    service = create_resource_pool_service(experience_database, access=access)
    pool_id = service.create_pool(ResourcePool("Pool", capacity_fte=1))
    identity = service.create_assignment(PoolAssignment(pool_id, 1, 0.5))
    body = f'''
from app.main import create_resource_pool_service
from app.presentation.components.resource_pool_dialogs import _confirm_unassign
_confirm_unassign(create_resource_pool_service(runtime, access=access), {pool_id}, {identity}, "Project")
'''
    app = native_screen(body, experience_database, access).run()
    assert not app.exception and service.get_assignment_by_id(identity)
    app.button(key=f"cancel_unassign_{identity}").click().run()
    assert not app.exception and service.get_assignment_by_id(identity)
    app.button(key=f"confirm_unassign_{identity}").click().run()
    assert not app.exception and service.get_assignment_by_id(identity) is None
    assert service.get_pool_by_id(pool_id)


def test_action_table_registers_in_each_application_runtime() -> None:
    body = '''
from app.presentation.components.action_table import action_table
action_table([{"id": 1, "name": "<script>"}], [("name", "Name")], {"remove": "Remove"}, key="table")
'''
    assert not AppTest.from_string(body).run().exception
    assert not AppTest.from_string(body).run().exception
