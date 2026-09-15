"""Pool classifications require identities and terminate parent traversal."""
from dataclasses import replace
import pytest
from app.domain.resources.models import ResourcePool
from app.domain.resources.rules import normalize_pool
from app.domain.resources.pool_types import PoolType, normalize_pool_type


@pytest.mark.parametrize("identity", [None, 0, -1, True, "1", 1.5])
def test_resource_pool_requires_a_positive_pool_type(identity):
    with pytest.raises(ValueError, match="pool type"):
        normalize_pool(ResourcePool("Pool", pool_type_id=identity))


def test_default_pool_type_is_human_and_explicit_selection_is_preserved():
    assert normalize_pool(ResourcePool("Human pool")).pool_type_id == 1
    assert normalize_pool(ResourcePool("Car pool", pool_type_id=2)).pool_type_id == 2


def test_type_names_and_translations_are_normalized():
    item = normalize_pool_type(PoolType(" Vans ", parent_pool_type_id=2,
        translations={"fr": " Camionnettes "}), [PoolType("Car", id=2)])
    assert item.name == "Vans" and item.parent_pool_type_id == 2
    assert item.label("fr") == "Camionnettes" and item.label("de") == "Vans"
    assert item.translations["en"] == "Vans"


@pytest.mark.parametrize("item", [PoolType(""), PoolType("x" * 121),
    PoolType("Name", parent_pool_type_id=True), PoolType("Name", id=999),
    PoolType("Name", translations={"xx": "Name"}), PoolType("Name", translations={"fr": " "})])
def test_invalid_pool_types_are_rejected(item):
    with pytest.raises(ValueError):
        normalize_pool_type(item, [])


def test_parent_validation_rejects_missing_parents_and_cycles():
    records = [PoolType("Root", id=1), PoolType("Child", id=2, parent_pool_type_id=1)]
    for parent in (1, 2):
        with pytest.raises(ValueError, match="circular"):
            normalize_pool_type(replace(records[0], parent_pool_type_id=parent), records)
    with pytest.raises(ValueError, match="parent.*no longer exists"):
        normalize_pool_type(PoolType("Orphan", parent_pool_type_id=99), records)
    assert normalize_pool_type(replace(records[1], parent_pool_type_id=None), records).parent_pool_type_id is None
