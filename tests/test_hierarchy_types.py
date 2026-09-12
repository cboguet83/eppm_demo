"""Shared hierarchy catalog, optional assignments, migration, and authorization."""

from contextlib import closing
from dataclasses import replace
import sqlite3

import pytest

from app.application.exceptions import OrganizationConflictError, ResourcePoolConflictError
from app.domain.access.models import AccessDenied
from app.domain.hierarchy import HierarchyType, normalize_hierarchy_type, validate_hierarchy_type_id
from app.domain.organization.models import Team
from app.domain.resources.models import ResourcePool, ResourcePoolGroup
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.hierarchy_migration import migrate_hierarchy_types
from app.infrastructure.database.schema_init import init_db
from app.operator_services import create_organization_service, create_resource_pool_service
from tests.test_business_transaction_security import business as business


@pytest.fixture
def catalog(tmp_path):
    path = str(tmp_path / "hierarchy.db")
    init_db(path)
    return path, create_organization_service(path), create_resource_pool_service(path)


def test_catalog_seed_labels_edits_and_reinitialization_preserve_customizations(catalog):
    path, organization, resources = catalog
    original = organization.get_all_hierarchy_types()
    assert [row.code for row in original] == [
        "ressort", "service", "division", "equipe", "region", "brigade", "district",
    ]
    assert resources.get_all_hierarchy_types() == original
    changed = replace(original[0], translations={"en": "Department", "fr": "Ressort"})
    assert organization.save_hierarchy_type(changed) == changed.id
    assert organization.get_all_hierarchy_types()[0].label("fr") == "Ressort"
    assert organization.get_all_hierarchy_types()[0].label("de") == "Department"
    assert organization.delete_hierarchy_type(original[-1].id)
    init_db(path)
    assert len(organization.get_all_hierarchy_types()) == 6
    assert organization.get_all_hierarchy_types()[0] == changed
    assert not organization.delete_hierarchy_type(999)
    with pytest.raises(ValueError, match="no longer exists"):
        organization.save_hierarchy_type(HierarchyType("missing", {"en": "Missing"}, 999))
    with pytest.raises(ValueError, match="cannot be changed"):
        organization.save_hierarchy_type(replace(changed, code="renamed"))
    with pytest.raises(OrganizationConflictError):
        organization.save_hierarchy_type(HierarchyType("ressort", {"en": "Duplicate"}))


@pytest.mark.parametrize("kind", ["team", "pool", "group"])
def test_optional_assignments_round_trip_and_protect_referenced_types(catalog, kind):
    path, organization, resources = catalog
    type_id = organization.save_hierarchy_type(HierarchyType("custom", {"en": "Custom"}))
    create, read, update, record, identity, conflict = {
        "team": (organization.create_team, organization.get_team_by_id, organization.update_team,
                 Team("Team"), "team_id", OrganizationConflictError),
        "pool": (resources.create_pool, resources.get_pool_by_id, resources.update_pool,
                 ResourcePool("Pool"), "id", ResourcePoolConflictError),
        "group": (resources.create_pool_group, resources.get_pool_group_by_id, resources.update_pool_group,
                  ResourcePoolGroup("Group"), "id", ResourcePoolConflictError),
    }[kind]
    record_id = create(record)
    assert read(record_id).hierarchy_type_id is None
    assert update(replace(read(record_id), hierarchy_type_id=type_id))
    assert read(record_id).hierarchy_type_id == type_id
    with pytest.raises(OrganizationConflictError):
        organization.delete_hierarchy_type(type_id)
    assert organization.get_all_hierarchy_types()[-1].id == type_id
    with pytest.raises(conflict):
        update(replace(read(record_id), hierarchy_type_id=99999))
    assert read(record_id).hierarchy_type_id == type_id
    assert update(replace(read(record_id), hierarchy_type_id=None))
    assert organization.delete_hierarchy_type(type_id)
    name_field = "team_name" if kind == "team" else "name"
    assigned_id = create(replace(record, hierarchy_type_id=1, **{name_field: "Assigned"}))
    assert getattr(read(assigned_id), identity) == assigned_id
    assert read(assigned_id).hierarchy_type_id == 1
    with closing(get_db(path)) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_preserves_existing_rows_and_is_atomic():
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE schema_migration(version TEXT PRIMARY KEY)")
        for table in ("team", "resource_pool", "resource_pool_group"):
            connection.execute(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY,name TEXT)")
            connection.execute(f"INSERT INTO {table} VALUES(7,'Existing')")
        connection.commit()
        with pytest.raises(RuntimeError), connection:
            connection.execute("BEGIN")
            migrate_hierarchy_types(connection)
            raise RuntimeError("Rollback migration")
        assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name='hierarchy_type'").fetchone()
        with connection:
            connection.execute("BEGIN")
            migrate_hierarchy_types(connection)
            migrate_hierarchy_types(connection)
        for table in ("team", "resource_pool", "resource_pool_group"):
            assert connection.execute(f"SELECT * FROM {table}").fetchall() == [(7, "Existing", None)]
        assert connection.execute("SELECT count(*) FROM hierarchy_type").fetchone()[0] == 7
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE hierarchy_type SET code='new' WHERE id=1")


@pytest.mark.parametrize("value", [True, 0, -1, "1", 1.5])
def test_invalid_hierarchy_id_is_rejected(value):
    with pytest.raises(ValueError):
        validate_hierarchy_type_id(value)


@pytest.mark.parametrize("value", [
    HierarchyType("Bad", {"en": "Label"}), HierarchyType("", {"en": "Label"}),
    HierarchyType("valid"), HierarchyType("valid", {"xx": "Label"}),
    HierarchyType("valid", {"en": " "}), HierarchyType("valid", {"en": "x" * 121}),
])
def test_invalid_catalog_values_are_rejected(value):
    with pytest.raises(ValueError):
        normalize_hierarchy_type(value)


def test_labels_have_safe_fallbacks_and_normalize_whitespace():
    value = normalize_hierarchy_type(HierarchyType(" code ", {"fr": " Libellé "}))
    assert value.code == "code" and value.label("fr") == "Libellé"
    assert value.label("en") == "code"
    validate_hierarchy_type_id(None)


def test_hierarchy_catalog_requires_shared_settings_authority(business):
    path, _, _, editor, manager = business
    from app.main import create_organization_service as authorized_organization
    from app.main import create_resource_pool_service as authorized_resources

    denied = authorized_organization(path, access=editor)
    with pytest.raises(AccessDenied):
        denied.get_all_hierarchy_types()
    with pytest.raises(AccessDenied):
        denied.save_hierarchy_type(HierarchyType("denied", {"en": "Denied"}))
    with pytest.raises(AccessDenied):
        denied.delete_hierarchy_type(1)
    with pytest.raises(AccessDenied):
        authorized_resources(path, access=editor).get_all_hierarchy_types()
    assert len(authorized_organization(path, access=manager).get_all_hierarchy_types()) == 7
