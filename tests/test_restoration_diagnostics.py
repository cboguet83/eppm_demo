"""Keep failure-only restoration observations bounded and credential-free."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.postgresql.test_mapping_allocation import (
    _report_restoration_failure, _restoration_snapshot,
)


def test_restoration_snapshot_omits_unexpected_server_and_browser_values(
    tmp_path: Path,
) -> None:
    """Do not expose extra fields if future instrumentation adds sensitive data."""
    sensitive = 'private-value-must-not-appear'
    record = {
        'kind': 'read', 'include_deleted': True, 'count': 2, 'deleted': 1,
        'unexpected': sensitive,
    }
    with (tmp_path / 'restoration-counts.jsonl').open('w') as stream:
        stream.write(json.dumps(record) + '\n')
    page = MagicMock()
    page.evaluate.return_value = {
        'checkboxChecked': True, 'treeRows': 2, 'deletedRows': 1,
        'scriptState': 'notRunning', 'unexpected': sensitive,
    }
    page.get_by_role.return_value.count.return_value = 2
    page.locator.return_value.count.return_value = 1
    completion = MagicMock(_completed=2, _running=False)

    result = _restoration_snapshot(page, completion, tmp_path)

    assert sensitive not in result
    state = json.loads(result)
    assert state['server_counts'] == [{
        'kind': 'read', 'include_deleted': True, 'count': 2, 'deleted': 1,
    }]
    assert state['dom'] == {
        'checkboxChecked': True, 'treeRows': 2, 'deletedRows': 1,
        'scriptState': 'notRunning',
    }
    assert state['successful_runs'] == 2
    assert state['script_running'] is False


def test_restoration_snapshot_reports_missing_observations_without_error_payloads(
    tmp_path: Path,
) -> None:
    """Diagnostic failures must not expose browser errors or hide their absence."""
    playwright = pytest.importorskip('playwright.sync_api')
    page = MagicMock()
    page.evaluate.side_effect = playwright.Error('private-value-must-not-appear')
    completion = MagicMock(_completed=0, _running=True)

    result = _restoration_snapshot(page, completion, tmp_path)

    assert 'private-value' not in result
    assert json.loads(result) == {
        'successful_runs': 0, 'script_running': True,
        'server_counts_unavailable': 'FileNotFoundError',
        'dom_unavailable': 'Error',
    }


@pytest.mark.parametrize('failure_kind', ['assertion', 'browser'])
def test_diagnostic_report_preserves_original_failure(
    tmp_path: Path, failure_kind: str,
) -> None:
    """An observation must not swallow or replace the originating failure."""
    playwright = pytest.importorskip('playwright.sync_api')
    error = (AssertionError('original failure') if failure_kind == 'assertion'
             else playwright.TimeoutError('original timeout'))
    page = MagicMock()
    page.evaluate.return_value = {}
    page.get_by_role.return_value.count.return_value = 0
    page.locator.return_value.count.return_value = 0
    completion = MagicMock(_completed=0, _running=False)

    with pytest.raises(type(error)) as caught:
        with _report_restoration_failure(page, completion, tmp_path):
            raise error

    assert caught.value is error
    assert error.__notes__[0].startswith('Restoration browser diagnostics: ')
    assert 'server_counts_unavailable' in error.__notes__[0]
