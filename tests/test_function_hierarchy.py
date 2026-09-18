"""Reporting tree and CSV boundary regressions."""

import pytest

from app.application.services.function_csv import parse_functions
from app.application.ports.references import FunctionReference
from app.domain.organization.models import OrgFunction
from app.presentation.components.function_tree import function_rows
from app.presentation.components.organization_frames import functions_frame


def test_planning_function_references_support_derived_reports_without_deleted_flag():
    frame = functions_frame([FunctionReference(1, 'Manager', None),
                             FunctionReference(2, 'Member', 1)])
    assert frame['has_reports'].tolist() == [True, False]
    assert frame['deleted_flag'].tolist() == [False, False]
    assert frame['name'].tolist() == ['Manager', 'Member']


def test_deleted_function_children_do_not_count_as_reports():
    frame = functions_frame([OrgFunction('Manager', 1),
        OrgFunction('Former member', 2, manager_function_id=1, deleted_flag=True)])
    assert frame['has_reports'].tolist() == [False, False]


def test_tree_sorts_leaves_then_containers_and_marks_deleted_rows():
    records = [OrgFunction('Root', 1), OrgFunction('Container', 2, manager_function_id=1),
               OrgFunction('Z leaf', 3, manager_function_id=1),
               OrgFunction('A leaf', 4, manager_function_id=1, deleted_flag=True),
               OrgFunction('Nested', 5, manager_function_id=2)]
    rows = function_rows(records, {})
    assert [row['id'] for row in rows] == [1, 4, 3, 2, 5]
    assert rows[1]['deleted'] and rows[0]['has_children']
    assert all('hierarchy_level' not in row and 'has_reports' not in row for row in rows)
    assert rows[-1]['depth'] == 2


@pytest.mark.parametrize('content', [b'name\n', b'name,name\nA,B', b'name,deleted_flag\nA,maybe',
    b'function_id,name\n1,A\n1,B', b'name,fte_percentage\nA,101', b'name,manager_function_id\nA,-1',
    b'name,hierarchy_level\nArchitect,3'])
def test_csv_rejects_invalid_records(content):
    with pytest.raises(ValueError):
        parse_functions(content)


def test_csv_accepts_bom_semicolon_and_optional_values():
    records = parse_functions('\ufeffname;deleted_flag\nArchitect;true'.encode())
    assert records == [OrgFunction('Architect', deleted_flag=True)]
