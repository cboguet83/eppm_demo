"""Private native scope semantics agree with domain validation and stable IDs."""

from copy import deepcopy

import psycopg
from psycopg.types.json import Jsonb
import pytest

from app.domain.access.models import normalize_scope
from tests.postgresql.test_integrity import business as business, execute


SCOPES = [
    None, True, "all", [], {}, {"kind": "all"},
    {"kind": "all", "project_ids": [], "conditions": []},
    {"kind": "all", "project_ids": None}, {"kind": "all", "extra": 1},
    {"kind": "projects", "project_ids": [1, 2, 1]}, {"kind": "projects", "project_ids": []},
    {"kind": "projects", "project_ids": [True]}, {"kind": "projects", "project_ids": [1.0]},
    {"kind": "projects", "project_ids": ["1"]}, {"kind": "projects", "project_ids": [-1]},
    {"kind": "projects", "project_ids": [9223372036854775808]},
    {"kind": "projects", "project_ids": [1], "conditions": [{}]},
    {"kind": "properties", "conditions": []}, {"kind": "properties", "conditions": [None]},
    {"kind": "properties", "conditions": [{"property_id": "project_type_id", "operator": "in", "value_ids": [1, 2]}]},
    {"kind": "properties", "conditions": [{"property_id": "project_type_id", "operator": "eq", "value_ids": [1, 1]}]},
    {"kind": "properties", "conditions": [{"property_id": "project_type_id", "operator": "eq", "value_ids": [1, 2]}]},
    {"kind": "properties", "conditions": [{"property_id": "project_type_id", "operator": "not", "value_ids": [1]}]},
    {"kind": "properties", "conditions": [{"property_id": "project_type_id", "operator": None, "value_ids": [1]}]},
    {"kind": "properties", "conditions": [{"property_id": 1, "operator": "eq", "value_ids": [1]}]},
    {"kind": "properties", "conditions": [{"property_id": "", "operator": "eq", "value_ids": [1]}]},
    {"kind": "properties", "conditions": [{"property_id": "P" * 129, "operator": "eq", "value_ids": [1]}]},
    {"kind": "properties", "conditions": [{"property_id": "P", "operator": "eq", "value_ids": [1], "extra": 1}]},
]


@pytest.mark.parametrize("document", SCOPES)
def test_native_structure_validation_matches_domain_normalization(pg_database, document):
    original = deepcopy(document)
    try:
        normalize_scope(document)
        valid = True
    except ValueError:
        valid = False
    with psycopg.connect(pg_database.operator_url) as operator:
        assert operator.execute("SELECT eppm.valid_scope_structure(%s)", (Jsonb(document),)).fetchone()[0] is valid
    assert document == original


def resolve(pg_database, document):
    with psycopg.connect(pg_database.operator_url) as operator:
        return operator.execute("SELECT eppm.resolve_scope(%s)", (Jsonb(document),)).fetchone()[0]


def categorical_scope(property_id, values, *, operator="in"):
    return {"kind": "properties", "conditions": [{"property_id": property_id, "operator": operator, "value_ids": values}]}


def test_scope_resolution_validates_every_reference_before_matching(pg_database, business):
    assert resolve(pg_database, {"kind": "all"}) == [1, 2]
    assert resolve(pg_database, {"kind": "projects", "project_ids": [2, 1, 2]}) == [1, 2]
    assert resolve(pg_database, categorical_scope("project_type_id", [1])) == [1, 2]
    for document in ({"kind": "projects", "project_ids": [1, 999]},
                     categorical_scope("project_type_id", [1, 999]),
                     categorical_scope("budget", [1]), categorical_scope("enum:0", [1]),
                     categorical_scope("enum:999999999999999999999999", [1]), {"kind": "invalid"}):
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            resolve(pg_database, document)


def seed_categorical(business):
    execute(business, "INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES ('REGION','Region','ENUM')", write=True)
    scope_id = execute(business, "SELECT id FROM eppm.app_scope_property WHERE param_id='REGION'")[0][0]
    values = execute(business, "INSERT INTO eppm.schema_param_options(param_id,option_value) VALUES ('REGION','North'),('REGION','South') RETURNING id", write=True)
    execute(business, """INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value)
        VALUES (1,'REGION','text','North'),(2,'REGION','text','South')""", write=True)
    return scope_id, [row[0] for row in values]


def test_categorical_conditions_intersect_and_track_value_edits(pg_database, business):
    scope_id, options = seed_categorical(business)
    north = categorical_scope(f"enum:{scope_id}", [options[0]])
    assert resolve(pg_database, north) == [1]
    both = categorical_scope(f"enum:{scope_id}", options)
    both["conditions"].append({"property_id": "project_type_id", "operator": "eq", "value_ids": [1]})
    assert resolve(pg_database, both) == [1, 2]
    execute(business, "UPDATE eppm.project_property_value SET text_value='South' WHERE project_id=1", write=True)
    assert resolve(pg_database, north) == []
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        resolve(pg_database, categorical_scope(f"enum:{scope_id}", [options[0], 999]))


def add_grant(business, scope):
    execute(business, "INSERT INTO eppm.app_user(created_at,updated_at) VALUES (1,1) ON CONFLICT DO NOTHING", write=True)
    return execute(business, """INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
        VALUES (1,'project_viewer',%s,1,'test') RETURNING id""", (Jsonb(scope),), write=True)[0][0]


@pytest.mark.parametrize("change", ["delete", "replace"])
def test_deleted_and_replaced_categorical_options_permanently_invalidate_grants(pg_database, business, change):
    scope_id, options = seed_categorical(business)
    scope = categorical_scope(f"enum:{scope_id}", [options[0]])
    grant = add_grant(business, scope)
    if change == "delete":
        execute(business, "DELETE FROM eppm.schema_param_options WHERE id=%s", (options[0],), write=True)
    else:
        execute(business, "UPDATE eppm.schema_param_options SET option_value='Other' WHERE id=%s", (options[0],), write=True)
        execute(business, "UPDATE eppm.schema_param_options SET option_value='North' WHERE id=%s", (options[0],), write=True)
    assert execute(business, "SELECT invalid_reason FROM eppm.app_role_assignment WHERE id=%s", (grant,))[0][0]


def test_retyped_scope_property_is_tombstoned_instead_of_reusing_its_identity(pg_database, business):
    scope_id, options = seed_categorical(business)
    scope = categorical_scope(f"enum:{scope_id}", [options[0]])
    execute(business, "UPDATE eppm.schema_parameters SET param_type='TEXT' WHERE param_id='REGION'", write=True)
    assert execute(business, "SELECT param_id FROM eppm.app_scope_property WHERE id=%s", (scope_id,)) == [(None,)]
    execute(business, "UPDATE eppm.schema_parameters SET param_type='ENUM' WHERE param_id='REGION'", write=True)
    new_id = execute(business, "SELECT id FROM eppm.app_scope_property WHERE param_id='REGION'")[0][0]
    assert new_id > scope_id
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        resolve(pg_database, scope)


@pytest.mark.parametrize("kind", ["project", "project_type"])
def test_deleted_named_scope_references_do_not_revive_after_id_reuse(business, kind):
    if kind == "project":
        grant = add_grant(business, {"kind": "projects", "project_ids": [1]})
        execute(business, "DELETE FROM eppm.project WHERE id=1", write=True)
        execute(business, "INSERT INTO eppm.project(id,name) VALUES (1,'Different project')", write=True)
    else:
        execute(business, "INSERT INTO eppm.project_type(id,name) VALUES (2,'Unused')", write=True)
        grant = add_grant(business, categorical_scope("project_type_id", [2]))
        execute(business, "DELETE FROM eppm.project_type WHERE id=2", write=True)
        execute(business, "INSERT INTO eppm.project_type(id,name) VALUES (2,'Different type')", write=True)
    assert execute(business, "SELECT invalid_reason FROM eppm.app_role_assignment WHERE id=%s", (grant,))[0][0]
