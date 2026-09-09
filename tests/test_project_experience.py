"""Persistence and modal regressions for the project experience improvements."""

from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.domain.organization.models import Employee
from app.domain.resources.models import PoolAssignment, ResourcePool
from app.infrastructure.database.project_experience_migration import migrate_project_experience
from app.infrastructure.database.schema_init import init_db
from app.main import (
    create_collaboration_service, create_maintenance_service, create_organization_service,
    create_project_service, create_resource_pool_service, create_schema_service,
)
from app.presentation.components.property_labels import property_label


@pytest.fixture
def experience_database(tmp_path: Path) -> str:
    path = str(tmp_path / "experience.db")
    init_db(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("INSERT INTO function(function_id,name,hierarchy_level) VALUES(1,'Engineer',1),(2,'Lead',1)")
    organization = create_organization_service(path)
    organization.create_employee(Employee("Alice", "Smith", "alice@example.invalid", "E1", function_id=1, mobile="+352 621 111 111", landline="+352 27 111 111"))
    organization.create_employee(Employee("Bob", "Jones", "bob@example.invalid", "E2", function_id=2, mobile="+352 621 222 222", landline="+352 27 222 222"))
    create_project_service(path).create_project(name="Project")
    return path


def project_dialog(path: str, operation: str, locale: str = "en") -> AppTest:
    """Keep a production project dialog mounted during full AppTest reruns."""
    return AppTest.from_string(f'''
from app.main import create_project_workspace
from app.presentation.components.project_dialogs import open_create_project_dialog, open_edit_project_dialog
from app.presentation.i18n import set_current_locale
set_current_locale({locale!r})
workspace = create_project_workspace({path!r})
{operation}
''', default_timeout=20).run()


def test_employee_landline_is_normalized_persisted_and_resolved_for_contacts(experience_database: str) -> None:
    organization = create_organization_service(experience_database)
    employee = organization.get_employee_by_id(1)
    organization.update_employee(replace(employee, landline="  +352 27 000 999  "))
    assert organization.get_employee_by_id(1).landline == "+352 27 000 999"
    service = create_collaboration_service(experience_database)
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


def test_clean_default_seeding_populates_every_employee_landline(tmp_path: Path) -> None:
    path = str(tmp_path / "seed.db")
    create_maintenance_service(path).startup()
    employees = create_organization_service(path).get_all_employees()
    assert employees and all(employee.mobile and employee.landline for employee in employees)
    assert len({employee.landline for employee in employees}) == len(employees)


def test_additive_migration_preserves_old_employee_values_and_is_idempotent(experience_database: str) -> None:
    with closing(sqlite3.connect(experience_database)) as connection, connection:
        connection.execute("DROP TABLE schema_parameter_translation")
        connection.execute("ALTER TABLE employee DROP COLUMN landline")
        connection.execute("DELETE FROM schema_migration WHERE version='project-experience-v1'")
    init_db(experience_database)
    init_db(experience_database)
    with closing(sqlite3.connect(experience_database)) as connection:
        assert connection.execute("SELECT mobile,landline FROM employee WHERE employee_id=1").fetchone() == ("+352 621 111 111", "")
        assert connection.execute("SELECT COUNT(*) FROM schema_migration WHERE version='project-experience-v1'").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_rolls_back_column_when_translation_table_creation_fails(experience_database: str) -> None:
    with closing(sqlite3.connect(experience_database)) as connection:
        with connection:
            connection.execute("ALTER TABLE employee DROP COLUMN landline")
            connection.execute("DELETE FROM schema_migration WHERE version='project-experience-v1'")
        with pytest.raises(sqlite3.OperationalError, match="already exists"):
            with connection:
                connection.execute("BEGIN")
                migrate_project_experience(connection)
        assert "landline" not in {row[1] for row in connection.execute("PRAGMA table_info(employee)")}
        assert not connection.execute("SELECT 1 FROM schema_migration WHERE version='project-experience-v1'").fetchone()


def test_translated_alias_falls_back_to_default_alias_then_name(experience_database: str) -> None:
    service = create_schema_service(experience_database)
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


def test_alias_table_enforces_nonblank_values_and_references(experience_database: str) -> None:
    service = create_schema_service(experience_database)
    service.create_parameter("p", None, "Property", "TEXT")
    with closing(sqlite3.connect(experience_database)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for values in (("missing", "fr", "Name"), ("p", "fr", " "), ("p", " ", "Name")):
            with pytest.raises(sqlite3.IntegrityError), connection:
                connection.execute("INSERT INTO schema_parameter_translation VALUES(?,?,?)", values)


def test_project_creation_uses_property_tabs_and_localized_alias_labels(experience_database: str) -> None:
    service = create_schema_service(experience_database)
    group = service.create_group("Custom section", 1)
    service.create_parameter("p", group, "internal_name", "TEXT", alias="Default alias")
    service.set_alias_translation("p", "fr", "Nom traduit")
    app = project_dialog(experience_database, "open_create_project_dialog(workspace)", "fr")
    assert not app.exception
    assert "Custom section" in [tab.label for tab in app.tabs]
    assert app.text_input(key="portfolio_create_2_p").label == "Nom traduit"
    assert not app.expander


def test_project_delete_requires_confirmation_and_cancel_preserves_project(experience_database: str) -> None:
    service = create_project_service(experience_database)
    app = project_dialog(experience_database, "open_edit_project_dialog(1, workspace)")
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


def test_unassignment_confirmation_and_cancel_preserve_pool_membership(experience_database: str) -> None:
    service = create_resource_pool_service(experience_database)
    pool_id = service.create_pool(ResourcePool("Pool", capacity_fte=1))
    identity = service.create_assignment(PoolAssignment(pool_id, 1, 0.5))
    body = f'''
from app.main import create_resource_pool_service
from app.presentation.components.resource_pool_dialogs import _confirm_unassign
_confirm_unassign(create_resource_pool_service({experience_database!r}), {pool_id}, {identity}, "Project")
'''
    app = AppTest.from_string(body).run()
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
