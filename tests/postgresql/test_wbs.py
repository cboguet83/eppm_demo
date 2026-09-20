"""WBS composition, native constraints, retained references and atomic claims."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import psycopg
import pytest

from app.application.services.business_access import BusinessAccess
from app.application.services.wbs import WbsService
from app.domain.access.models import AccessDenied
from app.infrastructure.postgresql.migration import discover_migrations, migrate
from app.main import create_project_service, create_settings_workspace
from app.operator_services import create_maintenance_service
from app.runtime import RuntimeResources
from tests.postgresql.test_portfolio_project_modal import business, dashboard_business, runtime
from tests.test_wbs import save_allocation


def catalog(resources: RuntimeResources, access: BusinessAccess) -> WbsService:
    """Resolve the real shared-catalog service from native Settings composition."""
    return create_settings_workspace(resources, access=access).wbs


def test_catalog_is_admin_owned_and_reference_edits_preserve_assignments(business):
    resources, _, _, editor, manager = business
    service = catalog(resources, manager)
    identity = service.save("A.1", "Description")
    assert service.can_manage() and not catalog(resources, editor).can_manage()
    for operation in (lambda: catalog(resources, editor).save("B"), lambda: catalog(resources, editor).delete(identity),
                      lambda: catalog(resources, editor).list_catalog()):
        with pytest.raises(AccessDenied):
            operation()
    projects = create_project_service(resources, access=editor)
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


def test_hidden_projects_reduce_availability_and_failed_save_rolls_back_every_field(business, authorized):
    resources, _, _, editor, manager = business
    identity = catalog(resources, manager).save("SHARED")
    admin_projects, projects = create_project_service(resources, access=manager), create_project_service(resources, access=editor)
    save_allocation(admin_projects, 2, [{"wbs_id": identity, "percentage": 60}])
    save_allocation(projects, 1, [{"wbs_id": identity, "percentage": 20}])
    assert projects.get_wbs_options(1)[0]["available"] == 40
    with pytest.raises(AccessDenied):
        projects.get_wbs_allocations(2)
    assert authorized.query("SELECT project_id FROM eppm.project_wbs") == [(1,)]
    with pytest.raises(ValueError, match="only 40%"):
        save_allocation(projects, 1, [{"wbs_id": identity, "percentage": 41}], name="Must roll back",
                        custom_links=[{"alias": "Docs", "url": "https://example.test"}])
    assert projects.get_project_by_id(1).name == "Visible"
    assert projects.get_links(1) == []
    assert projects.get_wbs_allocations(1) == [{"wbs_id": identity, "percentage": 20}]
    save_allocation(projects, 1, [{"wbs_id": identity, "percentage": 40}])
    assert catalog(resources, manager).list_catalog()[0]["available"] == 0
    # Ordinary callers that do not edit WBS retain their existing assignments.
    save_allocation(projects, 1, None)
    assert projects.get_wbs_allocations(1)[0]["percentage"] == 40


def test_new_project_wbs_save_is_atomic_and_multiple_codes_are_independent(business, authorized):
    resources, _, _, _, manager = business
    service, projects = catalog(resources, manager), create_project_service(resources, access=manager)
    first, second = service.save("A"), service.save("B")
    identity = projects.create_project(name="New", wbs_allocations=[{"wbs_id": first, "percentage": 100}, {"wbs_id": second, "percentage": 100}])
    assert len(projects.get_wbs_allocations(identity)) == 2
    with pytest.raises(ValueError, match="only 0%"):
        projects.create_project(name="Rejected", wbs_allocations=[{"wbs_id": first, "percentage": 1}])
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.project WHERE name='Rejected'").fetchone()[0] == 0
    with pytest.raises(ValueError, match="no longer exists"):
        save_allocation(projects, identity, [{"wbs_id": 999, "percentage": 0}])
    assert projects.delete_project(identity)
    assert projects.get_wbs_options()[0]["available"] == 100


def test_cancellation_releases_wbs_and_reactivation_validates_retained_shares(business):
    resources, _, _, _, manager = business
    projects = create_project_service(resources, access=manager)
    identity = catalog(resources, manager).save('CANCELLED')
    save_allocation(projects, 1, [{'wbs_id': identity, 'percentage': 100}])
    first = projects.get_project_by_id(1)
    projects.update_project(1, first.name, 'Cancelled', first.dynamic_attributes)
    assert projects.get_wbs_options(2)[0]['available'] == 100
    save_allocation(projects, 2, [{'wbs_id': identity, 'percentage': 80}])
    with pytest.raises(ValueError, match='Resolve its WBS allocation conflict.*only 20%'):
        projects.update_project(1, first.name, 'In Progress', first.dynamic_attributes)
    assert projects.get_project_by_id(1).status == 'Cancelled'
    assert projects.get_wbs_allocations(1) == [{'wbs_id': identity, 'percentage': 100}]
    projects.update_project(1, first.name, 'In Progress', first.dynamic_attributes,
                            wbs_allocations=[{'wbs_id': identity, 'percentage': 20}])
    assert projects.get_project_by_id(1).status == 'In Progress'
    assert projects.get_wbs_options()[0]['available'] == 0


def test_concurrent_wbs_reactivation_and_claim_cannot_exceed_cap(business):
    resources, _, _, _, manager = business
    projects = create_project_service(resources, access=manager)
    identity = catalog(resources, manager).save('RESTORE-RACE')
    save_allocation(projects, 1, [{'wbs_id': identity, 'percentage': 100}])
    project = projects.get_project_by_id(1)
    projects.update_project(1, project.name, 'Cancelled', project.dynamic_attributes)
    ready = Barrier(2)

    def save(restore):
        service = create_project_service(resources, access=manager)
        ready.wait(timeout=10)
        try:
            if restore:
                service.update_project(1, project.name, 'In Progress', project.dynamic_attributes)
            else:
                save_allocation(service, 2, [{'wbs_id': identity, 'percentage': 100}])
            return 'saved'
        except ValueError:
            return 'rejected'

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(save, [True, False])) == ['rejected', 'saved']
    assert projects.get_wbs_options()[0]['available'] == 0


def test_direct_database_constraints_guard_caps_fractions_references_and_owner_changes(business, authorized):
    """SQL must reject fractional shares before rounding and preserve owner checks."""
    resources, _, _, editor, manager = business
    identity = catalog(resources, manager).save("DB")
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_wbs VALUES(1,%s,70),(2,%s,30)", (identity, identity))
    for query, args, error in [
        ("UPDATE eppm.project_wbs SET percentage=31 WHERE project_id=2", (), psycopg.errors.CheckViolation),
        ("UPDATE eppm.project_wbs SET percentage=2.5 WHERE project_id=2", (), psycopg.errors.CheckViolation),
        ("INSERT INTO eppm.project_wbs VALUES(999,%s,0)", (identity,), psycopg.errors.ForeignKeyViolation),
        ("INSERT INTO eppm.project_wbs VALUES(1,%s,0)", (identity,), psycopg.errors.UniqueViolation),
        ("UPDATE eppm.wbs SET code='##bad'", (), psycopg.errors.CheckViolation),
    ]:
        with psycopg.connect(authorized.setup.operator_url) as connection:
            with pytest.raises(error):
                connection.execute(query, args)
    for query in ("UPDATE eppm.project_wbs SET percentage=0 WHERE project_id=2",
                  "DELETE FROM eppm.project_wbs WHERE project_id=2"):
        # Native RLS hides the target entirely; no forbidden row can be changed.
        assert resources.database.run(lambda connection: connection.execute(query).rowcount,
                                      write=True, bind=authorized.binding(1)) == 0
    for query in ("UPDATE eppm.project_wbs SET project_id=2 WHERE project_id=1",
                  "UPDATE eppm.wbs SET description='Forbidden'"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            authorized.query(query, write=True)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT project_id,percentage FROM eppm.project_wbs ORDER BY project_id").fetchall() == [(1,70),(2,30)]
        assert connection.execute("SELECT description FROM eppm.wbs").fetchone() == ("",)


def test_competing_saves_serialize_and_only_one_can_claim_the_remaining_capacity(business):
    resources, _, _, _, manager = business
    identity = catalog(resources, manager).save("RACE")
    ready = Barrier(2)

    def claim(project_id):
        projects = create_project_service(resources, access=manager)
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
    assert catalog(resources, manager).list_catalog()[0]["available"] == 40


@pytest.mark.parametrize("value", ["0.1", "99.9", "-0.1", "100.1", "NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("operation", ["insert", "update"])
def test_runtime_sql_rejects_fractional_and_nonfinite_wbs_shares(business, authorized, value, operation):
    """Reject exact external input in native SQL without changing a valid share."""
    resources, _, _, editor, manager = business
    identity = catalog(resources, manager).save("WHOLE")
    projects = create_project_service(resources, access=editor)
    if operation == "update":
        save_allocation(projects, 1, [{"wbs_id": identity, "percentage": 35}])
        query = "UPDATE eppm.project_wbs SET percentage=%s WHERE project_id=1 AND wbs_id=%s"
    else:
        query = "INSERT INTO eppm.project_wbs(percentage,wbs_id,project_id) VALUES(%s,%s,1)"
    with pytest.raises(psycopg.errors.CheckViolation):
        authorized.query(query, (Decimal(value), identity), write=True)
    assert projects.get_wbs_allocations(1) == (
        [{"wbs_id": identity, "percentage": 35}] if operation == "update" else []
    )


def test_wbs_read_contracts_keep_integer_percentages(business, authorized):
    """Exact native storage preserves the project and dashboard integer DTOs."""
    from app.main import create_dashboard_service

    resources, _, _, editor, manager = business
    identity = catalog(resources, manager).save("INTEGER")
    authorized.query("INSERT INTO eppm.project_wbs VALUES(1,%s,%s)", (identity, Decimal("35.0")), write=True)
    projects = create_project_service(resources, access=editor)
    assert type(projects.get_wbs_allocations(1)[0]["percentage"]) is int
    dashboard = create_dashboard_service(resources, access=editor)
    assert type(dashboard.reader.data([1]).shares[0].percentage) is int


def test_whole_share_upgrade_preserves_existing_values_and_reenters_cleanly(empty_database, tmp_path):
    """Upgrade the previously applied schema instead of rewriting its migration."""
    previous = tmp_path / "previous"
    previous.mkdir()
    for migration in discover_migrations()[:20]:
        (previous / migration.name).write_bytes(migration.sql.encode("utf-8"))
    migrate(empty_database.operator_url, directory=previous)
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES('General',true)")
        connection.execute("INSERT INTO eppm.project(name) VALUES('Retained')")
        connection.execute("INSERT INTO eppm.wbs(code) VALUES('ZERO'),('PART'),('FULL')")
        connection.execute("INSERT INTO eppm.project_wbs VALUES(1,1,0),(1,2,35),(1,3,100)")
    assert migrate(empty_database.operator_url) == tuple(item.name for item in discover_migrations()[20:])
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute("SELECT wbs_id,percentage FROM eppm.project_wbs ORDER BY wbs_id").fetchall() == [(1,0),(2,35),(3,100)]
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute("UPDATE eppm.project_wbs SET percentage=35.1 WHERE wbs_id=2")
    assert migrate(empty_database.operator_url) == ()


def test_migration_is_repeatable_and_backed_up_resets_leave_no_orphan_allocations(business, authorized, clients, tmp_path):
    """Explicit reentry and both reset modes retain the original WBS contracts."""
    resources, _, _, editor, manager = business
    identity = catalog(resources, manager).save("PERSIST")
    projects = create_project_service(resources, access=editor)
    save_allocation(projects, 1, [{"wbs_id": identity, "percentage": 0}])
    assert migrate(authorized.setup.operator_url) == ()
    assert projects.get_wbs_allocations(1) == [{"wbs_id": identity, "percentage": 0}]
    maintenance = create_maintenance_service(authorized.setup.operator_url, backup_directory=tmp_path, archive_tools=clients)
    maintenance.flush()
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.project_wbs").fetchone() == (0,)
        assert connection.execute("SELECT code FROM eppm.wbs").fetchall() == [("PERSIST",)]
    assert len(list(tmp_path.glob("*.dump"))) == 1
    maintenance.flush(flush_all=True)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM eppm.wbs").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM eppm.project_wbs").fetchone() == (0,)
    assert len(list(tmp_path.glob("*.dump"))) == 2
