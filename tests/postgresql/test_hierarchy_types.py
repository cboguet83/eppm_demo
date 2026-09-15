"""Shared hierarchy catalog, optional assignments, migration, and authorization."""

from tests.postgresql.pool_helpers import create_container

from dataclasses import replace

import psycopg
from psycopg import sql
import pytest

from app.application.exceptions import OrganizationConflictError, ResourcePoolConflictError
from app.domain.access.models import AccessDenied
from app.domain.hierarchy import HierarchyType, normalize_hierarchy_type, validate_hierarchy_type_id
from app.domain.organization.models import Team
from app.domain.resources.models import ResourcePool
from app.infrastructure.postgresql.migration import migrate
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.main import create_organization_service, create_resource_pool_service
from app.runtime import RuntimeResources


@pytest.fixture
def catalog(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        ensure_reference_catalog(connection)
    runtime = RuntimeResources(authorized.database, authorized.key)
    access = authorized.binding(4).access
    return (authorized, create_organization_service(runtime, access=access),
            create_resource_pool_service(runtime, access=access))


def test_catalog_seed_labels_edits_and_reinitialization_preserve_customizations(catalog):
    authorized, organization, resources = catalog
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
    assert migrate(authorized.setup.operator_url) == ()
    with psycopg.connect(authorized.setup.operator_url) as connection:
        ensure_reference_catalog(connection)
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
    authorized, organization, resources = catalog
    type_id = organization.save_hierarchy_type(HierarchyType("custom", {"en": "Custom"}))
    create, read, update, record, identity, conflict = {
        "team": (organization.create_team, organization.get_team_by_id, organization.update_team,
                 Team("Team"), "team_id", OrganizationConflictError),
        "pool": (resources.create_pool, resources.get_pool_by_id, resources.update_pool,
                 ResourcePool("Pool"), "id", ResourcePoolConflictError),
        "group": (resources.create_pool, resources.get_pool_by_id, resources.update_pool,
                  ResourcePool("Group"), "id", ResourcePoolConflictError),
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
    table, key = {'team': ('team', 'team_id'), 'pool': ('resource_pool', 'id'),
                  'group': ('resource_pool', 'id')}[kind]
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        authorized.query(sql.SQL('UPDATE eppm.{} SET hierarchy_type_id=99999 WHERE {}=%s').format(
            sql.Identifier(table), sql.Identifier(key)), (assigned_id,), user_id=4, write=True)
    assert read(assigned_id).hierarchy_type_id == 1


def test_native_reference_install_is_atomic_and_reentry_preserves_existing_entities(authorized):
    runtime = RuntimeResources(authorized.database, authorized.key)
    access = authorized.binding(4).access
    organization = create_organization_service(runtime, access=access)
    resources = create_resource_pool_service(runtime, access=access)
    team = organization.create_team(Team('Existing team'))
    pool = resources.create_pool(ResourcePool('Existing pool'))
    group = create_container(resources, ResourcePool('Existing group'))
    before = (organization.get_team_by_id(team), resources.get_pool_by_id(pool),
              resources.get_pool_by_id(group))
    with pytest.raises(RuntimeError, match='Rollback reference'), psycopg.connect(authorized.setup.operator_url) as connection:
        ensure_reference_catalog(connection)
        raise RuntimeError('Rollback reference')
    assert organization.get_all_hierarchy_types() == []
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.operator_seed_state').fetchone() == (0,)
        ensure_reference_catalog(connection)
        ensure_reference_catalog(connection)
    assert migrate(authorized.setup.operator_url) == ()
    assert len(organization.get_all_hierarchy_types()) == 7
    assert (organization.get_team_by_id(team), resources.get_pool_by_id(pool),
            resources.get_pool_by_id(group)) == before
    assert all(entity.hierarchy_type_id is None for entity in before)
    type_id = organization.get_all_hierarchy_types()[0].id
    with pytest.raises(psycopg.errors.CheckViolation):
        authorized.query("UPDATE eppm.hierarchy_type SET code='new' WHERE id=%s", (type_id,), user_id=4, write=True)


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


def test_hierarchy_catalog_requires_shared_settings_authority(catalog):
    authorized, _, _ = catalog
    path = RuntimeResources(authorized.database, authorized.key)
    editor = authorized.binding(1).access
    manager = authorized.binding(4).access
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
