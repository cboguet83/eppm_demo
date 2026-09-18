"""Real database and Streamlit regression tests for project contacts and logs."""

from app.operator_services import create_maintenance_service
from app.main import create_project_service
from app.main import create_schema_service

from app.application.exceptions import CollaborationConflictError
from app.application.services.collaboration import CollaborationService
from app.application.services.business_access import BusinessAccess
from app.runtime import RuntimeResources
from app.infrastructure.postgresql.migration import migrate
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import native_screen, runtime as runtime, access as access

import pandas as pd

import psycopg

import pytest
from unittest.mock import patch

from app.domain.projects.collaboration import EVENT_STATUSES
from app.application.exceptions import CollaborationStorageError
from app.infrastructure.postgresql.collaboration import (
    PostgresCollaborationGateway,
    PostgresCollaborationStore,
)
from app.main import create_collaboration_service


@pytest.fixture
def database(runtime: RuntimeResources, authorized: AuthorizedFixture) -> RuntimeResources:
    """Prepare the original two-project directory through separate operator setup."""
    with psycopg.connect(authorized.setup.operator_url) as connection, connection.cursor() as cursor:
        connection.execute("DELETE FROM eppm.project WHERE id=3")
        cursor.executemany("UPDATE eppm.project SET name=%s WHERE id=%s", [("Alpha", 1), ("Beta", 2)])
        cursor.executemany(
            'INSERT INTO eppm.function(function_id,name) VALUES (%s,%s)',
            [(1, "Manager"), (2, "Architect"), (3, "Vacant function")],
        )
        cursor.executemany(
            'INSERT INTO eppm.employee(firstname,lastname,email,function_id)\n            VALUES (%s,%s,%s,%s)',
            [("Alice", "Smith", "alice@example.test", 1),
             ("Bob", "Jones", "bob@example.test", 2)],
        )
        connection.execute('INSERT INTO eppm.employee_function(employee_id,function_id) '
                           'SELECT employee_id,function_id FROM eppm.employee')
    return runtime


@pytest.fixture
def collaboration(database: RuntimeResources, access: BusinessAccess) -> CollaborationService:
    """Bind the collaboration use cases to a real native business-admin session."""
    return create_collaboration_service(database, access=access)


def event_values(repo):
    return dict(
        title="Review",
        description="Review scope",
        deadline="2027-02-28",
        scope="internal",
        comment="Initial comment",
        event_type_id=repo.list_catalog("event_type")[0]["id"],
    )


def test_roles_can_repeat_and_occupants_follow_the_function(collaboration, database, access, authorized):
    repo = collaboration
    role = repo.save_catalog("role", "Sponsor")
    first = repo.save_contact(1, role, 1)
    repo.save_contact(1, role, 2)
    repo.save_contact(2, role, 1)
    assert [row["person"] for row in repo.list_contacts(1)] == ["Alice Smith", "Bob Jones"]
    with pytest.raises(CollaborationConflictError):
        repo.save_contact(1, role, 1)
    with pytest.raises(CollaborationConflictError):
        repo.save_contact(1, role, 999)
    with pytest.raises(CollaborationConflictError):
        repo.delete_catalog("role", role)
    with pytest.raises(ValueError):
        repo.save_contact(2, role, 3, first)
    repo.save_contact(1, role, 3, first)
    assert repo.list_contacts(1)[0]["person"] == "Vacant function"
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("UPDATE eppm.employee_function SET function_id=3 WHERE employee_id="
                     "(SELECT employee_id FROM eppm.employee WHERE email='alice@example.test')")
    assert repo.list_contacts(1)[0]["person"] == "Alice Smith"
    repo.save_catalog("role", "Executive sponsor", role)
    assert repo.list_contacts(1)[0]["role"] == "Executive sponsor"
    repo.delete_contact(2, first)
    assert len(repo.list_contacts(1)) == 2


def test_migration_is_additive_idempotent_and_catalog_deletions_stick(collaboration, database, access, authorized):
    repo = collaboration
    assert {r["name"] for r in repo.list_catalog("event_type")} == {
        "General information",
        "Blocking Point",
        "Project update",
    }
    role = repo.save_catalog("role", "Sponsor")
    repo.save_contact(1, role, 1)
    event = repo.save_event(1, **event_values(repo))
    unused = repo.save_catalog("event_type", "Temporary")
    repo.delete_catalog("event_type", unused)
    default_unused = repo.list_catalog("event_type")[-1]["id"]
    repo.delete_catalog("event_type", default_unused)
    migrate(authorized.setup.operator_url)
    assert len(repo.list_catalog("event_type")) == 2
    assert repo.list_events(1)[0]["id"] == event
    assert repo.list_contacts(1)[0]["role_id"] == role
    assert len(pd.DataFrame(create_project_service(database, access=access).get_planning_catalog(tuple(parameter.param_id for parameter in create_schema_service(database, access=access).get_all_parameters())))) == 2
    with psycopg.connect(authorized.setup.operator_url) as conn:
        assert conn.execute("""SELECT count(*) FROM eppm.project_contact c
            LEFT JOIN eppm.project p ON p.id=c.project_id WHERE p.id IS NULL""").fetchone()[0] == 0


@pytest.mark.parametrize("status", EVENT_STATUSES)
def test_events_support_every_state_and_project_scoped_updates(collaboration, database, status, access, authorized):
    repo = collaboration
    values = event_values(repo)
    event = repo.save_event(1, **values, status=status)
    assert repo.list_events(1)[0]["status"] == status
    assert repo.list_events(2) == []
    values.update(scope="global", deadline=None, comment="Updated")
    repo.save_event(1, **values, status="closed", event_id=event)
    assert repo.list_events(1)[0]["comment"] == "Updated"
    assert repo.list_events(1)[0]["scope"] == "global"
    with pytest.raises(ValueError):
        repo.save_event(2, **values, event_id=event)
    with pytest.raises(CollaborationConflictError):
        repo.delete_catalog("event_type", values["event_type_id"])


@pytest.mark.parametrize(
    "field,value",
    [("title", "  "), ("deadline", "2027-02-30"), ("scope", "private"), ("status", "unknown")],
)
def test_event_validation_rolls_back_invalid_updates(collaboration, database, field, value, access, authorized):
    repo = collaboration
    values = event_values(repo)
    event = repo.save_event(1, **values)
    with pytest.raises(ValueError):
        repo.save_event(1, **{**values, field: value}, event_id=event)
    assert repo.list_events(1)[0]["title"] == "Review"
    assert repo.list_events(1)[0]["scope"] == "internal"


def test_catalog_validation_translations_and_project_deletion_cascade(collaboration, database, access, authorized):
    repo = collaboration
    role = repo.save_catalog("role", "Sponsor")
    with pytest.raises(CollaborationConflictError):
        repo.save_catalog("role", "sponsor")
    with pytest.raises(ValueError):
        repo.save_catalog("role", " ")
    with pytest.raises(ValueError):
        repo.list_catalog("untrusted_table")
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("INSERT INTO eppm.project_role_translation VALUES (%s, 'fr', 'Parrain')", (role,))
    repo.save_contact(1, role, 1)
    assert repo.list_contacts(1, "fr")[0]["role"] == "Parrain"
    assert repo.list_contacts(1, "de")[0]["role"] == "Sponsor"
    repo.save_event(1, **event_values(repo))
    with psycopg.connect(authorized.setup.operator_url) as conn:
        conn.execute("DELETE FROM eppm.project WHERE id=1")
        assert conn.execute("""SELECT count(*) FROM eppm.project_contact c
            LEFT JOIN eppm.project p ON p.id=c.project_id WHERE p.id IS NULL""").fetchone()[0] == 0
    assert repo.list_contacts(1) == repo.list_events(1) == []
    repo.delete_catalog("role", role)


def test_log_paging_and_backed_up_resets_leave_no_orphans(
    collaboration, database, access, authorized, clients, tmp_path,
):
    repo = collaboration
    for index in range(55):
        repo.save_event(1, **{**event_values(repo), "title": str(index)})
    assert len(repo.list_events(1)) == 50
    assert [r["title"] for r in repo.list_events(1, offset=50)] == ["4", "3", "2", "1", "0"]
    role = repo.save_catalog("role", "Sponsor")
    repo.save_contact(1, role, 1)
    maintenance = create_maintenance_service(
        authorized.setup.operator_url, backup_directory=tmp_path, archive_tools=clients,
    )
    maintenance.flush()
    assert repo.list_contacts(1) == repo.list_events(1) == []
    assert len(repo.list_catalog("role")) == 1
    maintenance.flush(flush_all=True)
    assert repo.list_catalog("role") == []
    assert len(repo.list_catalog("event_type")) == 3
    assert len(list(tmp_path.glob("*.dump"))) == 2
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.project_contact").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM eppm.project_log_event").fetchone()[0] == 0


def ui_app(database, access, body):
    if body.startswith(("_contact_dialog", "_remove_contact_dialog")):
        body += "\nrender_project_contacts(1, service)"
    elif body.startswith("_event_dialog"):
        body += "\nrender_project_log(1, service)"
    return native_screen(
        f"""
from app.presentation.i18n import set_current_locale
from app.main import create_collaboration_service
from app.presentation.pages.collaboration import render_project_contacts, render_project_log, render_project_catalog, _contact_dialog, _remove_contact_dialog, _event_dialog
set_current_locale('en')
service = create_collaboration_service(runtime, access=access)
{body}
""",
        database, access,
    ).run()


def test_contact_ui_adds_edits_and_removes_function_assignments(collaboration, database, access, authorized):
    from tests.modal_interactions import modal_state, submit_modal

    repo = collaboration
    role = repo.save_catalog("role", "Sponsor")
    app = ui_app(database, access, "render_project_contacts(1, service)")
    assert not app.exception
    assert not app.selectbox
    next(b for b in app.button if b.label == "Add contact").click().run()
    assert not app.exception and modal_state(app)["form"]["title"] == "Project contact"
    app = ui_app(database, access, "_contact_dialog(1, service)")
    submit_modal(app)
    assert not app.exception
    contact = repo.list_contacts(1)[0]
    assert contact["role_id"] == role and contact["person"] == "Alice Smith"
    app = ui_app(database, access, f"_contact_dialog(1, service, {contact['id']})")
    assert modal_state(app)["form"]["fields"][0]["disabled"]
    submit_modal(app, values={"function_id": "2"})
    assert not app.exception
    assert repo.list_contacts(1)[0]["person"] == "Bob Jones"
    app = ui_app(database, access, f"_remove_contact_dialog(1, service, {contact['id']})")
    submit_modal(app, cancel=True)
    assert repo.list_contacts(1)
    submit_modal(app)
    assert not app.exception
    assert repo.list_contacts(1) == []


def test_log_ui_creates_and_edits_all_fields(collaboration, database, access, authorized):
    from tests.modal_interactions import submit_modal

    repo = collaboration
    app = ui_app(database, access, "render_project_log(1, service)")
    assert not app.exception
    assert not app.text_input
    app.button(key="project_log_1_add").click().run()
    submit_modal(app, "log", {"title": "Approval", "description": "Needs approval",
                              "comment": "Review tomorrow", "scope": "global"})
    assert not app.exception
    event = repo.list_events(1)[0]
    assert event["title"] == "Approval" and event["scope"] == "global"
    with patch("app.presentation.components.action_table.action_table", return_value={"id": event["id"], "action": "edit"}):
        app.run()
    submit_modal(app, "log", {"status": "completed"})
    assert not app.exception
    assert repo.list_events(1)[0]["status"] == "completed"


def test_settings_catalog_ui_protects_used_entries_and_deletes_unused(collaboration, database, access, authorized):
    repo = collaboration
    app = ui_app(database, access, "render_project_catalog(service, 'role')")
    app.text_input[0].set_value("Sponsor")
    next(b for b in app.button if b.label == "Save").click().run()
    assert not app.exception
    role = repo.list_catalog("role")[0]["id"]
    repo.save_contact(1, role, 1)
    app.selectbox[0].select(role).run()
    app.checkbox[0].check().run()
    next(b for b in app.button if b.label == "Delete").click().run()
    assert not app.exception and app.error
    repo.delete_contact(1, repo.list_contacts(1)[0]["id"])
    next(b for b in app.button if b.label == "Delete").click().run()
    assert not app.exception
    assert repo.list_catalog("role") == []


def test_layered_catalog_rename_rolls_back_when_translation_write_fails(collaboration, database, access, authorized):
    service = create_collaboration_service(database, access=access)
    role = service.save_catalog("role", "Original")
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute(
            """CREATE FUNCTION eppm.reject_test_role_translation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'translation write failed' USING ERRCODE='23514'; END $$"""
        )
        connection.execute("""CREATE TRIGGER reject_role_translation BEFORE UPDATE
            ON eppm.project_role_translation FOR EACH ROW
            EXECUTE FUNCTION eppm.reject_test_role_translation()""")
    with pytest.raises(CollaborationConflictError) as failure:
        service.save_catalog("role", "Changed", role)
    assert failure.value.__cause__ is None
    assert "translation write failed" not in str(failure.value)
    assert service.list_catalog("role") == [{"id": role, "name": "Original", "label": "Original"}]
    with pytest.raises(ValueError, match="no longer exists"):
        service.save_catalog("role", "Missing", 999)


def test_collaboration_adapter_rejects_untrusted_catalog_identifiers(collaboration, database, access, authorized):
    gateway = PostgresCollaborationGateway(database.database, database.key, access=access)
    with pytest.raises(ValueError, match="Unknown project catalog"):
        gateway.run(lambda store: store.list_catalog("role; DROP TABLE eppm.project", "en"))
    assert len(create_project_service(database, access=access).get_planning_catalog()) == 2


def test_layered_contacts_use_one_snapshot_during_concurrent_deletion(collaboration, database, access, authorized):
    service = collaboration
    role = service.save_catalog("role", "Sponsor")
    service.save_contact(1, role, 3)
    read_contacts = PostgresCollaborationStore.list_contacts

    def delete_after_contact_read(store, project_id, locale):
        contacts = read_contacts(store, project_id, locale)
        with psycopg.connect(authorized.setup.operator_url) as writer:
            writer.execute("SET LOCAL statement_timeout='1s'")
            writer.execute("DELETE FROM eppm.project_contact WHERE function_id=3")
            writer.execute("DELETE FROM eppm.function WHERE function_id=3")
        assert read_contacts(store, project_id, locale) == contacts
        return contacts

    with patch.object(PostgresCollaborationStore, "list_contacts", delete_after_contact_read):
        contacts = service.list_contacts(1)
    assert len(contacts) == 1 and contacts[0]["person"] == "Vacant function"
    assert service.list_contacts(1) == []


def test_layered_gateway_rolls_back_all_writes_and_returns_usable_leases(collaboration, database, access, authorized):
    gateway = PostgresCollaborationGateway(database.database, database.key, access=access)

    def abort(store):
        store.save_catalog("role", "Partial", None)
        raise ValueError("Abort operation")

    with pytest.raises(ValueError, match="Abort operation"):
        gateway.run(abort, write=True)
    assert collaboration.list_catalog("role") == []
    role = collaboration.save_catalog("role", "Committed")
    assert collaboration.list_catalog("role") == [{"id": role, "name": "Committed", "label": "Committed"}]


def test_layered_storage_errors_do_not_expose_database_details(database, access, authorized, caplog):
    service = create_collaboration_service(database, access=access)
    database.database.close()
    with pytest.raises(CollaborationStorageError) as failure:
        service.list_catalog("role")
    assert failure.value.__cause__ is None
    assert authorized.setup.runtime_url not in str(failure.value) + caplog.text
    assert "DatabaseUnavailableError" in caplog.text


@pytest.mark.parametrize("field,value", [("description", None), ("comment", 5), ("deadline", 42)])
def test_layered_event_boundary_rejects_malformed_fields_before_writes(
    collaboration, database, field, value
, access, authorized):
    service = create_collaboration_service(database, access=access)
    with pytest.raises(ValueError):
        service.save_event(1, **{**event_values(collaboration), field: value})
    assert service.list_events(1) == []


def test_layered_event_paging_is_bounded_and_rejects_malformed_offsets(collaboration, database, access, authorized):
    values = event_values(collaboration)
    gateway = PostgresCollaborationGateway(database.database, database.key, access=access)

    def insert_events(store):
        for index in range(105):
            store.save_event(1, {**values, "title": str(index), "status": "new"}, None)

    gateway.run(insert_events, write=True)
    assert len(collaboration.list_events(1, limit=1000, offset=-1)) == 100
    assert [row["title"] for row in collaboration.list_events(1, limit=0)] == ["104"]
    with pytest.raises(ValueError, match="page"):
        collaboration.list_events(1, offset="bad")
    with pytest.raises(ValueError, match="page"):
        collaboration.list_events(1, limit=None)


def test_collaboration_ui_paging_and_event_date_editing(collaboration, database, access, authorized):
    from datetime import date

    for index in range(52):
        collaboration.save_event(1, **{**event_values(collaboration), "title": str(index)})
    app = ui_app(database, access, "render_project_log(1, service)")
    with patch("app.presentation.components.action_table.action_table", return_value=None) as table:
        app.button(key="project_log_1_next").click().run()
        assert not app.exception
        assert [row["title"] for row in table.call_args.args[0]] == ["1", "0"]
        assert {key for key, _ in table.call_args.args[1]} >= {"description", "comment"}
        assert table.call_args.kwargs["context_menu"] is True
    assert app.button(key="project_log_1_next").disabled
    app.button(key="project_log_1_previous").click().run()
    event_id = collaboration.list_events(1)[0]["id"]
    with patch("app.presentation.components.action_table.action_table", return_value={"id": event_id, "action": "edit"}):
        app.run()
    from tests.modal_interactions import submit_modal
    submit_modal(app, "log", {"deadline": "2027-03-01"})
    assert not app.exception
    assert collaboration.list_events(1)[0]["deadline"] == "2027-03-01"


def test_collaboration_ui_reports_validation_and_read_failures(collaboration, database, access, authorized):
    from tests.modal_interactions import modal_state, submit_modal

    app = ui_app(database, access, "_event_dialog(1, service)")
    submit_modal(app, "log")
    assert not app.exception
    assert modal_state(app, "log")["form"]["error"] == "Title is required."
    assert collaboration.list_events(1) == []
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("DROP TABLE eppm.project_log_event")
    app = ui_app(database, access, "render_project_log(1, service)")
    assert not app.exception
    assert "could not be accessed" in app.error[0].value
    assert "project_log_event" not in app.error[0].value


def test_collaboration_ui_handles_failed_write_without_success_state(collaboration, database, access, authorized):
    app = ui_app(database, access, "render_project_catalog(service, 'role')")
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.break_test_catalog() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
                PERFORM * FROM eppm.missing_internal_table; RETURN NEW; END $$""")
        connection.execute("""CREATE TRIGGER broken_catalog_write BEFORE INSERT
            ON eppm.project_role FOR EACH ROW EXECUTE FUNCTION eppm.break_test_catalog()""")
    app.text_input[0].set_value("Sponsor")
    next(button for button in app.button if button.label == "Save").click().run()
    assert not app.exception
    assert "could not be accessed" in app.error[0].value
    assert app.selectbox[0].value is None
    assert collaboration.list_catalog("role") == []


def test_collaboration_ui_explains_missing_configuration(collaboration, database, access, authorized):
    contacts = ui_app(database, access, "render_project_contacts(1, service)")
    assert not contacts.exception
    next(b for b in contacts.button if b.label == "Add contact").click().run()
    assert any("Create project roles" in message.value for message in contacts.info)
    for entry in collaboration.list_catalog("event_type"):
        collaboration.delete_catalog("event_type", entry["id"])
    events = ui_app(database, access, "render_project_log(1, service)")
    assert not events.exception
    assert any("Create event types" in message.value for message in events.info)
