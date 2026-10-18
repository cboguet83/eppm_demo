"""Business dictionary validation and authorized application commands."""

from unittest.mock import Mock

import pytest

from app.application.services.dictionaries import DictionaryService
from app.domain.access.models import Permission
from app.domain.dictionaries import dictionary_code, dictionary_edit, entry_id, locale_code


@pytest.mark.parametrize('value', ['project_role', 'project_event_type'])
def test_dictionary_codes_accept_only_supported_lists(value):
    assert dictionary_code(value) == value


@pytest.mark.parametrize('value', ['status', 'role', '', None, [], {}])
def test_dictionary_codes_reject_unknown_values(value):
    with pytest.raises(ValueError):
        dictionary_code(value)


@pytest.mark.parametrize('value', [True, False, 0, -1, 2**63, '1', None])
def test_entry_id_rejects_invalid_bigint_references(value):
    with pytest.raises(ValueError):
        entry_id(value)


@pytest.mark.parametrize('value', ['../private', '', 'x', 'en_', 'en-!', 'en-' + 'a'*40, None])
def test_locale_rejects_invalid_language_identifiers(value):
    with pytest.raises(ValueError):
        locale_code(value)


def test_edit_copies_submissions_normalizes_and_preserves_omissions():
    labels = {' FR ': ' Parrain ', 'de': ''}
    edit = dictionary_edit(' Sponsor ', labels)
    labels[' FR '] = 'Changed elsewhere'
    assert edit.name == 'Sponsor'
    assert edit.translations == {'fr': 'Parrain', 'de': '', 'en': 'Sponsor'}
    assert dictionary_edit('Name').translations == {'en': 'Name'}
    assert dictionary_edit('Name', {'en': 'Name'}).name == 'Name'
    assert locale_code(' DE-CH ') == 'de-ch'
    assert entry_id(2**63-1) == 2**63-1


@pytest.mark.parametrize('name,labels', [
    (' ', None), (None, None), ('Name', []), ('Name', {'fr': None}),
    ('Name', {'FR': 'One', 'fr': 'Two'}), ('Name', {'en': ''}),
    ('Name', {'en': 'Other'}), ('Name', {'../private': 'Bad'}),
])
def test_invalid_edits_fail_before_persistence(name, labels):
    gateway = Mock()
    with pytest.raises(ValueError):
        DictionaryService(gateway).save_entry('project_role', name, translations=labels)
    gateway.run.assert_not_called()


def test_service_uses_injected_store_and_shared_write_permission():
    store, gateway = Mock(), Mock()
    gateway.run.side_effect = lambda operation, **options: operation(store)
    service = DictionaryService(gateway)
    store.save_entry.return_value = 7
    assert service.save_entry('project_role', ' Sponsor ', 7, {'fr': 'Parrain'}) == 7
    code, edit, identity = store.save_entry.call_args.args
    assert (code, identity, edit.name) == ('project_role', 7, 'Sponsor')
    assert edit.translations == {'en': 'Sponsor', 'fr': 'Parrain'}
    assert gateway.run.call_args.kwargs == {'write': True, 'permission': Permission.SHARED}
    service.delete_entry('project_event_type', 9)
    store.delete_entry.assert_called_once_with('project_event_type', 9)
    assert gateway.run.call_args.kwargs['permission'] == Permission.SHARED
    service.list_entries('project_role', ' FR ')
    store.list_entries.assert_called_once_with('project_role', 'fr')
    service.translations('project_role', 7)
    store.translations.assert_called_once_with('project_role', 7)
