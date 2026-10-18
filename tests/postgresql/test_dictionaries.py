"""Shared dictionary persistence, label fallback and atomic administration."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest

from app.application.exceptions import DictionaryConflictError, DictionaryStorageError
from app.application.services.dictionaries import DictionaryService
from app.domain.access.models import AccessDenied
from app.infrastructure.postgresql.dictionaries import PostgresDictionaryGateway
from app.infrastructure.postgresql.errors import DatabaseUnavailableError, TransactionRetryError


def service(authorized, user_id=4):
    return DictionaryService(PostgresDictionaryGateway(
        authorized.database, authorized.key, access=authorized.binding(user_id).access))


def test_shared_dictionary_translation_edit_fallback_and_reference_lifetime(authorized):
    catalog = service(authorized)
    identity = catalog.save_entry('project_role', ' Sponsor ', translations={'fr': 'Parrain', 'de': 'Pate'})
    assert catalog.list_entries('project_role','fr') == [{'id':identity,'name':'Sponsor','label':'Parrain'}]
    assert catalog.list_entries('project_role','pt')[0]['label'] == 'Sponsor'
    assert catalog.translations('project_role',identity) == {'en':'Sponsor','fr':'Parrain','de':'Pate'}
    catalog.save_entry('project_role','Executive sponsor',identity, {'fr':''})
    assert catalog.list_entries('project_role','fr')[0]['label'] == 'Executive sponsor'
    assert catalog.translations('project_role',identity) == {'en':'Executive sponsor','de':'Pate'}
    assert authorized.query("SELECT code FROM eppm.business_dictionary_entry WHERE dictionary_code='project_role' AND id=%s", (identity,)) == [(f'entry_{identity}',)]
    with pytest.raises(DictionaryConflictError):
        catalog.save_entry('project_role','EXECUTIVE SPONSOR')
    catalog.save_entry('project_event_type','Executive sponsor')
    catalog.delete_entry('project_role',identity)
    assert catalog.list_entries('project_role') == []
    assert authorized.query("SELECT count(*) FROM eppm.business_dictionary_translation WHERE dictionary_code='project_role'") == [(0,)]
    catalog.delete_entry('project_role',identity)
    with pytest.raises(ValueError, match='no longer exists'):
        catalog.save_entry('project_role','Missing',identity)
    with pytest.raises(ValueError, match='no longer exists'):
        catalog.translations('project_role',identity)


def test_translation_failure_rolls_back_names_english_and_other_translations(authorized):
    catalog = service(authorized)
    identity = catalog.save_entry('project_event_type','Original',translations={'fr':'Original FR'})
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_dictionary_translation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
              IF NEW.label='Rejected' THEN RAISE EXCEPTION 'private cause' USING ERRCODE='23514'; END IF;
              RETURN NEW;
            END $$""")
        connection.execute('CREATE TRIGGER reject_label BEFORE INSERT OR UPDATE ON eppm.business_dictionary_translation '
                           'FOR EACH ROW EXECUTE FUNCTION eppm.reject_dictionary_translation()')
    with pytest.raises(DictionaryConflictError):
        catalog.save_entry('project_event_type','Changed',identity,{'fr':'Rejected','de':'Changed DE'})
    assert catalog.translations('project_event_type',identity) == {'en':'Original','fr':'Original FR'}
    assert catalog.list_entries('project_event_type')[0]['name'] == 'Original'


def test_dictionary_service_denies_nonadministrators_without_changing_labels(authorized):
    catalog = service(authorized)
    identity = catalog.save_entry('project_role','Sponsor')
    reader = service(authorized,1)
    assert reader.list_entries('project_role')[0]['id'] == identity
    assert reader.translations('project_role',identity) == {'en':'Sponsor'}
    with pytest.raises(AccessDenied):
        reader.save_entry('project_role','Denied',identity,{'fr':'Denied'})
    with pytest.raises(AccessDenied):
        reader.delete_entry('project_role',identity)
    assert catalog.list_entries('project_role')[0]['name'] == 'Sponsor'


def test_concurrent_dictionary_edits_replay_complete_translation_commands(authorized):
    identity = service(authorized).save_entry('project_role','Original')
    barrier = Barrier(2)
    attempts = [0,0]
    class GatedGateway(PostgresDictionaryGateway):
        def run(self, operation, **options):
            def callback(store):
                attempts[self.index] += 1
                if attempts[self.index] == 1:
                    barrier.wait(timeout=10)
                return operation(store)
            return super().run(callback, **options)
    def rename(index):
        gateway = GatedGateway(authorized.database,authorized.key,access=authorized.binding(4).access)
        gateway.index = index
        return DictionaryService(gateway).save_entry('project_role',str(index),identity,{'fr':str(index)})
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(rename,range(2))) == [identity,identity]
    labels = service(authorized).translations('project_role',identity)
    assert labels['en'] == labels['fr'] == service(authorized).list_entries('project_role')[0]['name']
    assert sum(attempts) >= 3


@pytest.mark.parametrize('failure', [psycopg.OperationalError, DatabaseUnavailableError, TransactionRetryError])
def test_dictionary_gateway_storage_failures_are_safe(authorized, monkeypatch, caplog, failure):
    def fail(*args, **kwargs):
        raise failure('private database details')
    monkeypatch.setattr('app.infrastructure.postgresql.dictionaries.run_business',fail)
    with pytest.raises(DictionaryStorageError) as raised:
        service(authorized).list_entries('project_role')
    assert 'private database details' not in str(raised.value) + caplog.text
