"""Native template/default contracts, protected audit and concurrent callbacks."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, Event

import psycopg
import pytest

from app.application.exceptions import ProjectTypeConflictError, ProjectTypeStorageError
from app.application.services.project_types import ProjectTypeService
from app.domain.access.models import AccessDenied, Permission
from app.infrastructure.postgresql.project_types import PostgresProjectTypeGateway
from app.infrastructure.postgresql.property_store import read_values, write_value


@pytest.fixture
def templates(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        for param_id, kind in [('text', 'TEXT'), ('none', 'TEXT'), ('blank', 'TEXT'), ('list', 'MULTI_ENUM'),
                               ('number', 'NUMBER'), ('date', 'DATE'), ('enum', 'ENUM'), ('tags', 'TAGS'),
                               ('url', 'URL'), ('hyperlink', 'HYPERLINK')]:
            connection.execute('INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES (%s,%s,%s)', (param_id, param_id, kind))
            if kind in {'ENUM', 'MULTI_ENUM'}:
                connection.execute("INSERT INTO eppm.schema_param_options(param_id,option_value,display_order) VALUES (%s,'A',1),(%s,'B',2)", (param_id, param_id))
    gateway = PostgresProjectTypeGateway(authorized.database, authorized.key, access=authorized.binding(4).access)
    return ProjectTypeService(gateway)


def template_rows(service, type_id=1):
    return {row['param_id']: row for row in service.get_template(type_id)}


def test_type_crud_preserves_general_order_uniqueness_and_missing_id_behavior(templates):
    type_id = templates.create_type(' Rail ', ' Initial ')
    assert [(row.name, row.description) for row in templates.get_all_types()] == [('General', ''), ('Rail', 'Initial')]
    assert templates.get_all_types()[0].is_general is True
    templates.update_type(type_id, 'Road', 'Updated')
    assert templates.get_all_types()[1].description == 'Updated'
    with pytest.raises(ProjectTypeConflictError, match='already exists'):
        templates.create_type('ROAD')
    templates.delete_type(type_id)
    templates.delete_type(type_id)
    assert [row.name for row in templates.get_all_types()] == ['General']
    with pytest.raises(ValueError, match='Unknown project type'):
        templates.update_type(type_id, 'Deleted')
    with pytest.raises(ValueError, match='Unknown project type'):
        templates.get_template(type_id)
    with pytest.raises(ValueError, match='cannot be renamed'):
        templates.update_type(1, 'Renamed General')
    with pytest.raises(ValueError, match='cannot be deleted'):
        templates.delete_type(1)
    templates.update_type(1, 'General', 'Changed description')
    assert templates.get_all_types()[0].description == 'Changed description'


def test_applicability_failure_rolls_back_flag_membership_and_protected_audit(templates, authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        before = connection.execute('SELECT count(*) FROM eppm.app_security_audit').fetchone()
    with pytest.raises(ProjectTypeConflictError):
        templates.set_applicability('text', False, [999])
    assert templates.get_applicability('text').applies_to_all is True
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.app_security_audit').fetchone() == before
    templates.set_applicability('text', False, [1, 1])
    with pytest.raises(ProjectTypeConflictError):
        templates.set_applicability('text', False, [1, 999])
    assert templates.get_applicability('text').type_ids == (1,)
    for operation in (lambda: templates.get_applicability('missing'), lambda: templates.set_applicability('missing', True)):
        with pytest.raises(ValueError, match='Unknown property'):
            operation()
    other = templates.create_type('Other')
    assert 'text' not in template_rows(templates, other)
    with pytest.raises(ValueError, match='does not apply'):
        templates.save_rule(other, 'text')
    templates.set_applicability('text', True)
    assert templates.get_applicability('text').type_ids == ()
    assert 'text' in template_rows(templates, other)


def test_deletion_guards_preserve_assigned_projects_and_exclusive_properties(templates, authorized):
    type_id = templates.create_type('Assigned')
    templates.set_applicability('text', False, [type_id])
    with pytest.raises(ValueError, match='exclusive properties'):
        templates.delete_type(type_id)
    templates.set_applicability('text', True)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project SET project_type_id=%s WHERE id=1', (type_id,))
    with pytest.raises(ValueError, match='Reassign'):
        templates.delete_type(type_id)
    assert templates.get_all_types()[1].id == type_id


def test_defaults_keep_absent_null_empty_text_empty_list_and_selection_order_distinct(templates):
    submitted = {'none': None, 'blank': '', 'list': ['B', 'A'], 'tags': [],
                 'date': '2026-09-08', 'enum': 'B', 'url': 'https://example.test', 'hyperlink': 'https://example.test/path'}
    for param_id, value in submitted.items():
        templates.save_rule(1, param_id, False, has_default=True, default_value=value)
    rows = template_rows(templates)
    assert rows['text']['has_default'] is False
    assert {key: rows[key]['default_value'] for key in submitted} == submitted
    assert all(rows[key]['has_default'] and rows[key]['mandatory'] is False for key in submitted)
    rows['list']['default_value'].append('Not persisted')
    assert template_rows(templates)['list']['default_value'] == ['B', 'A']
    templates.save_rule(1, 'list', True, has_default=True, default_value=[])
    assert template_rows(templates)['list']['default_value'] == []
    templates.save_rule(1, 'list', None, has_default=False)
    assert template_rows(templates)['list']['has_default'] is False


@pytest.mark.parametrize('value', [Decimal('9007199254740993.1234567890123456789'), 9007199254740993, 0.125, Decimal('1E+400')])
def test_numeric_defaults_round_trip_as_exact_decimals_without_float_intermediates(templates, authorized, value):
    templates.save_rule(1, 'number', has_default=True, default_value=value)
    expected = Decimal(str(value))
    result = template_rows(templates)['number']['default_value']
    assert isinstance(result, Decimal) and result == expected
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute("SELECT number_value,pg_typeof(number_value)::text FROM eppm.project_type_property_default WHERE param_id='number'").fetchone() == (expected, 'numeric')


def test_invalid_default_rolls_back_the_rule_previous_default_and_audit(templates, authorized):
    templates.save_rule(1, 'enum', False, has_default=True, default_value='A')
    with psycopg.connect(authorized.setup.operator_url) as connection:
        before = connection.execute('SELECT count(*) FROM eppm.app_security_audit').fetchone()
    with pytest.raises(ValueError, match='invalid selection'):
        templates.save_rule(1, 'enum', True, has_default=True, default_value='Missing')
    row = template_rows(templates)['enum']
    assert row['mandatory'] is False and row['default_value'] == 'A'
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.app_security_audit').fetchone() == before


def test_native_audit_failure_rolls_back_the_complete_rule_and_selection_change(templates, authorized):
    templates.save_rule(1, 'list', False, has_default=True, default_value=['A'])
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.fail_template_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.details_json->>'table'='project_type_property_default_item' THEN
                RAISE EXCEPTION 'private audit diagnostic' USING ERRCODE='23514'; END IF; RETURN NEW; END $$""")
        connection.execute('CREATE TRIGGER fail_template_audit BEFORE INSERT ON eppm.app_security_audit FOR EACH ROW EXECUTE FUNCTION eppm.fail_template_audit()')
        before = connection.execute('SELECT count(*) FROM eppm.app_security_audit').fetchone()
    with pytest.raises(ProjectTypeConflictError) as error:
        templates.save_rule(1, 'list', True, has_default=True, default_value=['B', 'A'])
    assert 'private' not in str(error.value)
    row = template_rows(templates)['list']
    assert row['mandatory'] is False and row['default_value'] == ['A']
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.app_security_audit').fetchone() == before


def test_reader_can_inspect_template_references_but_cannot_administer_or_bypass_native_guards(templates, authorized):
    gateway = PostgresProjectTypeGateway(authorized.database, authorized.key, access=authorized.binding(1).access)
    reader = ProjectTypeService(gateway)
    assert reader.type_choices()[0].name == 'General'
    assert reader.template_reference(1)[0]['param_id'] == 'blank'
    for operation in (reader.get_all_types, lambda: reader.create_type('Denied'), lambda: reader.save_rule(1, 'text'),
                      lambda: gateway.run(lambda store: store.update_type(1, 'Bypass', ''), write=True)):
        with pytest.raises(AccessDenied):
            operation()
    assert templates.get_all_types()[0].name == 'General'


def test_property_values_read_as_one_scoped_join_preserving_parent_and_item_privacy(templates, authorized):
    def save(connection):
        write_value(connection, 1, 'tags', ['Visible second', 'Visible first'])
        write_value(connection, 1, 'number', Decimal('12.1234567890123456789'))
        write_value(connection, 2, 'text', None)
        write_value(connection, 3, 'tags', ['Hidden'])
    authorized.database.run(save, write=True, bind=authorized.binding(4))
    visible = authorized.database.run(lambda connection: read_values(connection), bind=authorized.binding(1))
    assert visible == {1: {'number': Decimal('12.1234567890123456789'), 'tags': ['Visible second', 'Visible first']}, 2: {'text': None}}
    assert authorized.database.run(lambda connection: read_values(connection, owner_id=3), bind=authorized.binding(1)) == {}
    assert authorized.database.run(lambda connection: read_values(connection, param_ids=['tags']), bind=authorized.binding(1)) == {1: {'tags': ['Visible second', 'Visible first']}}
    assert authorized.database.run(lambda connection: read_values(connection, param_ids=[]), bind=authorized.binding(1)) == {}
    with pytest.raises(ValueError, match='Unknown property'):
        authorized.database.run(lambda connection: write_value(connection, 1, 'missing', 'value'), write=True, bind=authorized.binding(4))


@pytest.mark.parametrize('table,owner', [('project_property_value', 'project_id'), ('project_type_property_default', 'project_type_id')])
@pytest.mark.parametrize('number', ['NaN', 'Infinity', '-Infinity'])
def test_native_constraints_reject_nonfinite_property_numbers_even_for_direct_sql(templates, authorized, table, owner, number):
    statement = psycopg.sql.SQL("INSERT INTO eppm.{}({},param_id,kind,number_value) VALUES (1,'number','number',%s)").format(
        psycopg.sql.Identifier(table), psycopg.sql.Identifier(owner))
    with pytest.raises(psycopg.errors.CheckViolation):
        authorized.query(statement, (Decimal(number),), user_id=4, write=True)


def test_value_reader_rejects_corrupt_scalar_selection_children(templates, authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) VALUES (1,'text','text','value')")
        connection.execute("INSERT INTO eppm.project_property_value_item(project_id,param_id,position,value) VALUES (1,'text',0,'invalid child')")
    with pytest.raises(ValueError, match='do not match'):
        authorized.database.run(lambda connection: read_values(connection), bind=authorized.binding(1))


def test_template_dates_remain_iso_strings_under_alternate_datestyle(templates, authorized):
    templates.save_rule(1, 'date', has_default=True, default_value='2026-09-08')
    def query(connection):
        connection.execute("SET LOCAL datestyle = 'German, DMY'")
        return read_values(connection, defaults=True, owner_id=1, param_ids=['date'])
    assert authorized.database.run(query, bind=authorized.binding(1)) == {1: {'date': '2026-09-08'}}


def test_multiquery_applicability_read_keeps_a_repeatable_snapshot(templates, authorized):
    read_started, write_finished = Event(), Event()
    gateway = PostgresProjectTypeGateway(authorized.database, authorized.key, access=authorized.binding(4).access)
    def read(store):
        before = store.get_applicability('text')
        read_started.set()
        assert write_finished.wait(10)
        return before, store.get_applicability('text')
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(gateway.run, read)
        assert read_started.wait(10)
        try:
            templates.set_applicability('text', False, [1])
        finally:
            write_finished.set()
        before, after = future.result(timeout=10)
    assert before == after and before.applies_to_all is True
    assert templates.get_applicability('text').applies_to_all is False


def test_concurrent_default_updates_replay_rule_and_ordered_selections_together(templates, authorized):
    templates.save_rule(1, 'list', None, has_default=True, default_value=[])
    barrier, attempts = Barrier(2), [0, 0]
    class GatedGateway(PostgresProjectTypeGateway):
        def __init__(self, index):
            super().__init__(authorized.database, authorized.key, access=authorized.binding(4).access)
            self.index = index
        def run(self, operation, **options):
            def callback(store):
                attempts[self.index] += 1
                if attempts[self.index] == 1:
                    barrier.wait(timeout=10)
                return operation(store)
            return super().run(callback, **options)
    def save(index):
        ProjectTypeService(GatedGateway(index)).save_rule(1, 'list', bool(index), has_default=True,
                                                        default_value=['B', 'A'] if index else ['A'])
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(save, range(2)))
    row = template_rows(templates)['list']
    assert row['default_value'] == (['B', 'A'] if row['mandatory'] else ['A'])
    assert sum(attempts) >= 3


def test_template_storage_outage_keeps_existing_safe_application_error(templates, authorized, caplog):
    authorized.database.close()
    with pytest.raises(ProjectTypeStorageError) as error:
        templates.get_all_types()
    assert 'postgresql://' not in str(error.value) + caplog.text


def test_inactive_defaults_and_overrides_return_when_applicability_is_restored(templates):
    other = templates.create_type('Other')
    templates.save_rule(other, 'text', True, has_default=True, default_value='Retained')
    templates.set_applicability('text', False, [1])
    assert 'text' not in template_rows(templates, other)
    templates.set_applicability('text', True)
    restored = template_rows(templates, other)['text']
    assert restored['mandatory'] is True and restored['default_value'] == 'Retained'


def test_concurrent_type_delete_and_exclusive_assignment_cannot_orphan_a_property(templates, authorized):
    type_id = templates.create_type('Concurrent')
    barrier = Barrier(2)
    class GatedGateway(PostgresProjectTypeGateway):
        def run(self, operation, **options):
            first = True
            def callback(store):
                nonlocal first
                if first:
                    first = False
                    barrier.wait(timeout=10)
                return operation(store)
            return super().run(callback, **options)
    def change(index):
        service = ProjectTypeService(GatedGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
        try:
            if index:
                service.set_applicability('text', False, [type_id])
            else:
                service.delete_type(type_id)
            return 'saved'
        except (ProjectTypeConflictError, ValueError):
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(change, range(2))) == ['conflict', 'saved']
    scope = templates.get_applicability('text')
    ids = {value.id for value in templates.get_all_types()}
    assert scope.applies_to_all or scope.type_ids == (type_id,) and type_id in ids


def test_retry_preserves_the_original_selection_command_if_callers_list_changes(templates, authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('CREATE SEQUENCE eppm.default_attempt')
        connection.execute('GRANT USAGE ON SEQUENCE eppm.default_attempt TO eppm_runtime')
        connection.execute("""CREATE FUNCTION eppm.retry_default_once() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF nextval('eppm.default_attempt')=1 THEN RAISE EXCEPTION 'Known rollback' USING ERRCODE='40001'; END IF;
            RETURN NEW; END $$""")
        connection.execute('CREATE TRIGGER retry_default_once BEFORE INSERT ON eppm.project_type_property_default_item FOR EACH ROW EXECUTE FUNCTION eppm.retry_default_once()')
    submitted, attempts = ['A'], []
    class ChangedInputGateway(PostgresProjectTypeGateway):
        def run(self, operation, **options):
            def callback(store):
                attempts.append(1)
                if len(attempts) == 2:
                    submitted[:] = ['B']
                return operation(store)
            return super().run(callback, **options)
    service = ProjectTypeService(ChangedInputGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    service.save_rule(1, 'list', has_default=True, default_value=submitted)
    assert submitted == ['B'] and len(attempts) == 2
    assert template_rows(templates)['list']['default_value'] == ['A']
