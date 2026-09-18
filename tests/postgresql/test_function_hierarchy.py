"""Function imports, hierarchy integrity and restoration against PostgreSQL."""

import csv
from dataclasses import replace
from io import StringIO

import psycopg
import pytest

from app.domain.organization.models import OrgFunction
from app.presentation.components.function_tree import function_rows
from tests.postgresql.test_organization import organization


def test_import_generates_ids_resolves_parents_and_preserves_missing_by_default(organization):
    original = organization.create_function(OrgFunction('Existing'))
    result = organization.import_functions_csv(b'function_id,name,manager_function_id\n9001,Parent,\n9002,Child,9001\n')
    assert (result.created, result.updated, result.deleted) == (2, 0, 0)
    records = {item.name: item for item in organization.get_all_functions()}
    assert records['Parent'].function_id != 9001
    assert records['Child'].manager_function_id == records['Parent'].function_id
    assert records['Existing'].function_id == original
    content = organization.export_csv('functions').encode()
    result = organization.import_functions_csv(content)
    assert (result.created, result.updated, result.deleted) == (0, 3, 0)
    assert 'has_reports' not in content.decode().splitlines()[0]
    assert 'hierarchy_level' not in content.decode().splitlines()[0]


def test_delete_missing_restore_and_export_visibility(organization):
    omitted = organization.create_function(OrgFunction('Omitted'))
    retained = organization.create_function(OrgFunction('Retained'))
    result = organization.import_functions_csv(f'function_id,name\n{retained},Kept\n'.encode(), delete_missing=True)
    assert result.deleted == 1
    assert len(list(csv.DictReader(StringIO(organization.export_csv('functions'))))) == 1
    assert len(list(csv.DictReader(StringIO(organization.export_csv('functions', include_deleted=True))))) == 2
    assert organization.undelete_function(omitted)
    assert not organization.undelete_function(omitted)
    assert len(organization.get_all_functions()) == 2


def test_hierarchy_rejects_cycles_and_parent_deletion_atomically(organization):
    parent = organization.create_function(OrgFunction('Parent'))
    child = organization.create_function(OrgFunction('Child', manager_function_id=parent))
    before = organization.get_all_functions()
    with pytest.raises(ValueError, match='cycle'):
        organization.update_function(replace(next(item for item in before if item.function_id == parent), manager_function_id=child))
    with pytest.raises(ValueError, match='deleted'):
        organization.delete_function(parent)
    with pytest.raises(ValueError, match='deleted'):
        organization.import_functions_csv(f'function_id,name,manager_function_id\n{child},Child,{parent}\n'.encode(), delete_missing=True)
    assert organization.get_all_functions() == before
    rows = function_rows(before, {})
    assert rows[0]['has_children']
    organization.delete_function(child)
    assert not function_rows(organization.get_all_functions(), {})[0]['has_children']


def test_invalid_import_rolls_back_new_rows_and_schema_removes_flag(organization, authorized):
    with pytest.raises(ValueError):
        organization.import_functions_csv(b'function_id,name,manager_function_id\n9001,A,9002\n9002,B,9001\n')
    assert not organization.get_all_functions(include_deleted=True)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='eppm' AND table_name='function' AND column_name='has_reports'").fetchone()[0] == 0
