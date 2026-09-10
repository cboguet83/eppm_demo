"""Real database invariants, concurrent allocation saves and WBS authorization."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
from threading import Barrier

import pytest

from app.application.services.wbs import WbsService
from app.domain.access.models import AccessDenied
from app.domain.projects.wbs import normalize_allocations, normalize_wbs
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.flush import flush_database
from app.infrastructure.database.schema_init import init_db
from app.infrastructure.repositories.projects import SqliteProjectGateway
from app.main import create_project_service
from tests.test_business_transaction_security import business as business, transaction


def catalog(path, access):
    return WbsService(SqliteProjectGateway(path, access=access))


def save_allocation(service, project_id, allocations, **overrides):
    project = service.get_project_by_id(project_id)
    arguments = dict(project_id=project_id, name=project.name, status=project.status,
                     planned_budget=project.planned_budget, actual_budget=project.actual_budget,
                     dynamic_attributes=project.dynamic_attributes, wbs_allocations=allocations)
    return service.update_project(**(arguments | overrides))


@pytest.mark.parametrize("code", ["WBS.01-A_2", "#TEMP-1", "abc", "ABC", "123", "_", "a" * 128])
def test_wbs_codes_keep_case_and_optional_fictive_prefix(code):
    assert normalize_wbs(" " + code + " ", " Description ") == (code, "Description")


@pytest.mark.parametrize("code", ["", "#", "##TEMP", "A B", "A/B", "A#B", "é", "a" * 129, None, 42])
def test_wbs_codes_reject_invalid_characters_and_empty_identifiers(code):
    with pytest.raises(ValueError):
        normalize_wbs(code, "")


@pytest.mark.parametrize("value", [-1, 101, 1.5, 100.0, True, "50", None])
def test_percentages_are_validated_without_rounding(value):
    with pytest.raises(ValueError, match="whole percentage"):
        normalize_allocations([{"wbs_id": 1, "percentage": value}])


@pytest.mark.parametrize("raw", [None, {}, [None], [{"wbs_id": 1}], [{"wbs_id": True, "percentage": 0}],
                                [{"wbs_id": 0, "percentage": 0}], [{"wbs_id": 2**63, "percentage": 0}],
                                [{"wbs_id": 1, "percentage": 0}] * 2])
def test_malformed_and_duplicate_assignments_are_rejected(raw):
    with pytest.raises(ValueError):
        normalize_allocations(raw)


def test_catalog_is_admin_owned_and_reference_edits_preserve_assignments(business):
    path, _, _, editor, manager = business
    service = catalog(path, manager)
    identity = service.save("A.1", "Description")
    assert service.can_manage() and not catalog(path, editor).can_manage()
    for operation in (lambda: catalog(path, editor).save("B"), lambda: catalog(path, editor).delete(identity),
                      lambda: catalog(path, editor).list_catalog()):
        with pytest.raises(AccessDenied):
            operation()
    projects = create_project_service(path, access=editor)
    save_allocation(projects, 1, [{"wbs_id": identity, "percentage": 35}])
    service.save("#NEW_1", "Updated", identity)
    assert projects.get_wbs_options(1) == [{"id": identity, "code": "#NEW_1", "description": "Updated", "available": 100}]
    with pytest.raises(ValueError, match="already exists"):
        service.save("#NEW_1")
    with pytest.raises(ValueError, match="assigned"):
        service.delete(identity)
    save_allocation(projects, 1, [])
    service.delete(identity)
    assert service.list_catalog() == []
    for operation in (lambda: service.delete(identity), lambda: service.save("Missing", "", identity)):
        with pytest.raises(ValueError, match="no longer exists"):
            operation()


def test_hidden_projects_reduce_availability_and_failed_save_rolls_back_every_field(business):
    path, _, _, editor, manager = business
    identity = catalog(path, manager).save("SHARED")
    admin_projects, projects = create_project_service(path, access=manager), create_project_service(path, access=editor)
    save_allocation(admin_projects, 2, [{"wbs_id": identity, "percentage": 60}])
    save_allocation(projects, 1, [{"wbs_id": identity, "percentage": 20}])
    assert projects.get_wbs_options(1)[0]["available"] == 40
    with pytest.raises(AccessDenied):
        projects.get_wbs_allocations(2)
    with transaction(path, editor) as connection:
        assert connection.execute("SELECT project_id FROM project_wbs").fetchall() == [(1,)]
    with pytest.raises(ValueError, match="only 40%"):
        save_allocation(projects, 1, [{"wbs_id": identity, "percentage": 41}], name="Must roll back",
                        custom_links=[{"alias": "Docs", "url": "https://example.test"}])
    assert projects.get_project_by_id(1).name == "Visible"
    assert projects.get_links(1) == []
    assert projects.get_wbs_allocations(1) == [{"wbs_id": identity, "percentage": 20}]
    save_allocation(projects, 1, [{"wbs_id": identity, "percentage": 40}])
    assert catalog(path, manager).list_catalog()[0]["available"] == 0
    # Ordinary callers that do not edit WBS retain their existing assignments.
    save_allocation(projects, 1, None)
    assert projects.get_wbs_allocations(1)[0]["percentage"] == 40


def test_new_project_wbs_save_is_atomic_and_multiple_codes_are_independent(business):
    path, _, _, _, manager = business
    service, projects = catalog(path, manager), create_project_service(path, access=manager)
    first, second = service.save("A"), service.save("B")
    identity = projects.create_project(name="New", wbs_allocations=[{"wbs_id": first, "percentage": 100}, {"wbs_id": second, "percentage": 100}])
    assert len(projects.get_wbs_allocations(identity)) == 2
    with pytest.raises(ValueError, match="only 0%"):
        projects.create_project(name="Rejected", wbs_allocations=[{"wbs_id": first, "percentage": 1}])
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT count(*) FROM project WHERE name='Rejected'").fetchone()[0] == 0
    with pytest.raises(ValueError, match="no longer exists"):
        save_allocation(projects, identity, [{"wbs_id": 999, "percentage": 0}])
    assert projects.delete_project(identity)
    assert projects.get_wbs_options()[0]["available"] == 100


def test_direct_database_constraints_guard_caps_fractions_references_and_owner_changes(business):
    path, _, _, editor, manager = business
    identity = catalog(path, manager).save("DB")
    with closing(get_db(path)) as connection, connection:
        connection.execute("INSERT INTO project_wbs VALUES(1,?,70)", (identity,))
        connection.execute("INSERT INTO project_wbs VALUES(2,?,30)", (identity,))
    for sql, args in [("UPDATE project_wbs SET percentage=31 WHERE project_id=2", ()),
                      ("UPDATE project_wbs SET percentage=2.5 WHERE project_id=2", ()),
                      ("INSERT INTO project_wbs VALUES(999,?,0)", (identity,)),
                      ("INSERT INTO project_wbs VALUES(1,?,0)", (identity,)),
                      ("UPDATE wbs SET code='##bad'", ())]:
        with closing(get_db(path)) as connection, connection, pytest.raises(sqlite3.IntegrityError):
            connection.execute(sql, args)
    for sql in ("UPDATE main.project_wbs SET percentage=0 WHERE project_id=2",
                "DELETE FROM main.project_wbs WHERE project_id=2",
                "UPDATE main.project_wbs SET project_id=2 WHERE project_id=1",
                "UPDATE main.wbs SET description='Forbidden'"):
        with pytest.raises(AccessDenied), transaction(path, editor) as connection:
            connection.execute(sql)


def test_competing_saves_serialize_and_only_one_can_claim_the_remaining_capacity(business):
    path, _, _, _, manager = business
    identity = catalog(path, manager).save("RACE")
    ready = Barrier(2)

    def claim(project_id):
        projects = create_project_service(path, access=manager)
        assert projects.get_wbs_options(project_id)[0]["available"] == 100
        ready.wait(timeout=10)
        try:
            save_allocation(projects, project_id, [{"wbs_id": identity, "percentage": 60}])
            return "saved"
        except ValueError as error:
            assert "only 40%" in str(error)
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(claim, [1, 2])) == ["rejected", "saved"]
    assert catalog(path, manager).list_catalog()[0]["available"] == 40


def test_migration_is_repeatable_and_flushes_leave_no_orphan_allocations(business):
    path, _, _, editor, manager = business
    identity = catalog(path, manager).save("PERSIST")
    projects = create_project_service(path, access=editor)
    save_allocation(projects, 1, [{"wbs_id": identity, "percentage": 0}])
    init_db(path)
    assert projects.get_wbs_allocations(1) == [{"wbs_id": identity, "percentage": 0}]
    flush_database(path)
    with closing(get_db(path)) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT count(*) FROM project_wbs").fetchone()[0] == 0
        assert connection.execute("SELECT code FROM wbs").fetchall() == [("PERSIST",)]
    flush_database(path, flush_all=True)
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT count(*) FROM wbs").fetchone()[0] == 0
