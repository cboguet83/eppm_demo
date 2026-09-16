"""CSV task identities survive edits and numbered dependency remapping."""

import csv
import io

import pytest

from app.domain.planning.csv_import import get_csv_template
from app.domain.planning.schedule_template import export_template, parse_template, template_content


def test_template_includes_blank_correlation_ids_for_new_tasks():
    rows = list(csv.DictReader(io.StringIO(get_csv_template())))
    assert all(row['task_correlation_id'] == '' for row in rows)
    content = template_content(parse_template(get_csv_template()))
    assert [task['id'] for task in content.tasks] == [-1, -2, -3]
    assert content.dependencies[0]['predecessor_task_id'] == -1


def test_csv_matches_id_despite_name_order_and_date_changes():
    steps = parse_template('step_number,task_correlation_id,task_name,start_date,end_date,preceding_step,dependency_type,dependency_lag\n'
                           '5,42,Renamed,2027-02-01,2027-02-02,,,\n'
                           '1,,New task,2027-02-03,2027-02-04,5,FS,0\n')
    content = template_content(steps)
    assert [task['id'] for task in content.tasks] == [42, -1]
    assert content.dependencies[0]['predecessor_task_id'] == 42
    assert content.dependencies[0]['task_id'] == -1
    exported = export_template([dict(content.tasks[0], id=99, task_correlation_id=42)], [])
    assert parse_template(exported)[0].task_correlation_id == 42


@pytest.mark.parametrize('identities', [('1', '1'), ('0', ''), ('-1', ''), ('abc', ''), ('9223372036854775808', '')])
def test_duplicate_or_invalid_correlations_are_rejected(identities):
    content = 'step_number,task_correlation_id,task_name,start_date,end_date\n'
    content += ''.join(f'{index},{identity},Task,2027-01-01,2027-01-02\n'
                       for index, identity in enumerate(identities, 1))
    with pytest.raises(ValueError, match='correlation'):
        parse_template(content)


def test_old_csv_without_correlation_column_creates_new_identities():
    content = template_content(parse_template('step_number,task_name,start_date,end_date\n1,New,2027-01-01,2027-01-02\n'))
    assert content.tasks[0]['id'] == -1
