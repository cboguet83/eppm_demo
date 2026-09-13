"""Full project saves validate all values while preserving unchanged storage."""

from decimal import Decimal

import psycopg
import pytest

from app.application.services.projects import ProjectService
from app.domain.access.models import AccessDenied
from app.infrastructure.postgresql.projects import PostgresProjectGateway, PostgresProjectStore
from app.infrastructure.postgresql.property_store import write_values


@pytest.fixture
def properties(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                'INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES (%s,%s,%s)',
                [(name, name, kind) for name, kind in [('text', 'TEXT'), ('none', 'TEXT'),
                 ('blank', 'TEXT'), ('list', 'MULTI_ENUM'), ('number', 'NUMBER'), ('date', 'DATE'),
                 ('enum', 'ENUM'), ('tags', 'TAGS')]],
            )
            cursor.executemany('INSERT INTO eppm.schema_param_options(param_id,option_value) VALUES (%s,%s)',
                               [(name, option) for name in ('list', 'enum') for option in ('A', 'B')])
    return {'text': 'Preserved', 'none': None, 'blank': '', 'list': ['B', 'A'], 'tags': [],
            'number': Decimal('9007199254740993.123456789'), 'date': '2026-09-13', 'enum': 'B'}


def _service(authorized, user_id: int = 4) -> ProjectService:
    return ProjectService(PostgresProjectGateway(authorized.database, authorized.key,
                          access=authorized.binding(user_id).access))


def _save(service: ProjectService, values: dict, *, project_id: int = 1, name: str = 'Saved') -> None:
    assert service.update_project(project_id, name, 'Draft', Decimal(0), Decimal(0), values)


def _storage(authorized) -> dict:
    with psycopg.connect(authorized.setup.operator_url) as connection:
        return {
            'parents': {row[0]: row[1:] for row in connection.execute(
                'SELECT param_id,xmin::text,kind,text_value,number_value,date_value '
                'FROM eppm.project_property_value WHERE project_id=1')},
            'items': connection.execute('SELECT param_id,position,value,xmin::text FROM eppm.project_property_value_item '
                                        'WHERE project_id=1 ORDER BY param_id,position').fetchall(),
            'revision': connection.execute('SELECT revision FROM eppm.project_cache_revision WHERE project_id=1').fetchone()[0],
            'security': connection.execute('SELECT revision FROM eppm.app_security_state').fetchone()[0],
            'audit': connection.execute('SELECT count(*) FROM eppm.app_security_audit').fetchone()[0],
        }


def test_title_save_preserves_all_unchanged_property_rows_and_only_advances_master_revision(authorized, properties):
    service = _service(authorized)
    _save(service, properties)
    before = _storage(authorized)

    _save(service, properties, name='New title')

    after = _storage(authorized)
    assert after == before | {'revision': before['revision'] + 1}
    assert service.get_project_by_id(1).name == 'New title'
    assert service.get_project_by_id(1).dynamic_attributes == properties


def test_mixed_save_changes_only_requested_representations_and_preserves_exact_values(authorized, properties):
    service = _service(authorized)
    _save(service, properties)
    before = _storage(authorized)
    changed = properties | {'list': ['A', 'B'], 'tags': ['Second', 'First'], 'none': '',
                            'number': Decimal('9007199254740993.123456788')}

    _save(service, changed)

    after = _storage(authorized)
    assert service.get_project_by_id(1).dynamic_attributes == changed
    for name in ('text', 'blank', 'date', 'enum'):
        assert after['parents'][name] == before['parents'][name]
    assert [row[:3] for row in after['items']] == [
        ('list', 0, 'A'), ('list', 1, 'B'), ('tags', 0, 'Second'), ('tags', 1, 'First')]
    assert after['parents']['none'] != before['parents']['none']


def test_equal_decoded_date_is_rewritten_when_definition_requires_text_storage(authorized, properties):
    service = _service(authorized)
    _save(service, properties)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.schema_parameters SET param_type='TEXT' WHERE param_id='date'")

    _save(service, properties)

    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT kind,text_value,date_value FROM eppm.project_property_value "
                                  "WHERE project_id=1 AND param_id='date'").fetchone() == ('text', '2026-09-13', None)


def test_unchanged_native_dates_remain_untouched_under_alternate_datestyle(authorized, properties):
    service = _service(authorized)
    _save(service, properties)
    before = _storage(authorized)

    def save(connection: psycopg.Connection) -> None:
        connection.execute("SET LOCAL datestyle = 'German, DMY'")
        store = PostgresProjectStore(connection)
        store.update(store.find(1))

    authorized.database.run(save, write=True, bind=authorized.binding(4))

    assert _storage(authorized) == before | {'revision': before['revision'] + 1}


def test_same_selection_is_still_validated_after_option_removal(authorized, properties):
    service = _service(authorized)
    _save(service, properties)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("DELETE FROM eppm.schema_param_options WHERE param_id='enum' AND option_value='B'")
    before = _storage(authorized)

    with pytest.raises(ValueError, match='invalid selection'):
        _save(service, properties, name='Must roll back')

    assert _storage(authorized) == before
    assert service.get_project_by_id(1).name == 'Saved'


def test_selection_position_gaps_are_normalized_even_when_decoded_order_matches(authorized, properties):
    service = _service(authorized)
    _save(service, properties)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.project_property_value_item SET position=position+10 "
                           "WHERE project_id=1 AND param_id='list'")
    assert service.get_project_by_id(1).dynamic_attributes == properties

    _save(service, properties)

    assert [row[1] for row in _storage(authorized)['items'] if row[0] == 'list'] == [0, 1]


def test_unchanged_values_do_not_bypass_owner_or_protected_property_permissions(authorized, properties):
    _save(_service(authorized), properties)
    _save(_service(authorized), properties, project_id=2)
    before = _storage(authorized)

    with pytest.raises(AccessDenied):
        _save(_service(authorized, 2), properties)
    with pytest.raises(AccessDenied):
        _save(_service(authorized, 1), properties, project_id=2)
    with pytest.raises(AccessDenied):
        _save(_service(authorized, 1), properties | {'enum': 'A'})
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.database.run(lambda connection: write_values(connection, 2, properties),
                                write=True, bind=authorized.binding(1))

    assert _storage(authorized) == before
    _save(_service(authorized, 1), properties, name='Allowed title edit')
    assert _storage(authorized) == before | {'revision': before['revision'] + 1}


def test_full_form_save_keeps_existing_overwrite_semantics_after_another_edit(authorized, properties):
    service = _service(authorized)
    _save(service, properties)
    _save(service, properties | {'text': 'Another edit'})

    _save(service, properties, name='Original full form')

    assert service.get_project_by_id(1).dynamic_attributes == properties
