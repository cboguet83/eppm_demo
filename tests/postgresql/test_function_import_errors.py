"""Import diagnostics identify user-correctable sources without leaking SQL."""

import re

import psycopg
import pytest

from app.application.exceptions import OrganizationStorageError
from app.domain.organization.models import OrgFunction
from tests.postgresql.test_organization import organization


@pytest.mark.parametrize(('column', 'value', 'reason'), [
    ('manager_function_id', '999', 'manager_function_id=999 is unknown'),
    ('dual_manager_function_id', '999', 'dual_manager_function_id=999 is unknown'),
    ('function_type_id', '999', 'function_type_id=999 does not identify an active function type'),
    ('fte_percentage', 'invalid', 'fte_percentage must be a whole number'),
])
def test_invalid_import_names_row_function_and_field_and_preserves_catalog(organization, column, value, reason):
    organization.create_function(OrgFunction('Retained'))
    before = organization.get_all_functions(include_deleted=True)
    with pytest.raises(ValueError) as caught:
        organization.import_functions_csv(f'name,{column}\nBroken,{value}\n'.encode(), delete_missing=True)
    assert 'Row 2, function "Broken"' in str(caught.value)
    assert reason in str(caught.value)
    assert organization.get_all_functions(include_deleted=True) == before


def test_cycle_reports_source_row_and_field_and_rolls_back_new_functions(organization):
    with pytest.raises(ValueError) as caught:
        organization.import_functions_csv(b'function_id,name,manager_function_id\n9001,A,9002\n9002,B,9001\n')
    message = str(caught.value)
    assert 'Row 2, function "A", function_id=9001' in message
    assert 'manager_function_id' in message and 'cycle' in message
    assert not organization.get_all_functions(include_deleted=True)


def test_delete_missing_error_identifies_retained_child_and_deleted_manager(organization):
    parent = organization.create_function(OrgFunction('Parent'))
    child = organization.create_function(OrgFunction('Child', manager_function_id=parent))
    before = organization.get_all_functions()
    with pytest.raises(ValueError) as caught:
        organization.import_functions_csv(f'function_id,name,manager_function_id\n{child},Child,{parent}\n'.encode(), delete_missing=True)
    message = str(caught.value)
    assert 'Row 2, function "Child"' in message and 'manager_function_id' in message
    assert f'"Parent" (ID {parent})' in message and 'delete-missing' in message
    assert organization.get_all_functions() == before


def test_deleted_import_invalid_type_reports_row_after_database_rejection(organization):
    with pytest.raises(ValueError) as caught:
        organization.import_functions_csv(b'name,function_type_id,deleted_flag\nFormer,999,true\n')
    assert 'Row 2, function "Former"' in str(caught.value)
    assert 'function_type_id references a missing record' in str(caught.value)
    assert not organization.get_all_functions(include_deleted=True)


def test_unexpected_database_failure_has_matching_safe_log_reference(organization, authorized, caplog):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('DROP VIEW eppm.active_function_type')
    with pytest.raises(OrganizationStorageError) as caught:
        organization.import_functions_csv(b'name\nNew function\n')
    message = str(caught.value)
    reference = re.search(r'Error reference: ([0-9a-f]{12})', message).group(1)
    assert reference in caplog.text and 'UndefinedTable' in caplog.text
    assert 'database operation failed' in message
    assert 'SELECT' not in message and 'active_function_type' not in message
    assert not organization.get_all_functions(include_deleted=True)
