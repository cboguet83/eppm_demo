"""Native schema settings, reference lifetimes and complete transaction replay."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import psycopg
from psycopg.types.json import Jsonb
import pytest

from app.application.exceptions import SchemaConflictError, SchemaStorageError
from app.application.services.project_types import ProjectTypeService
from app.application.services.schema import SchemaService
from app.domain.access.models import AccessDenied, Permission
from app.infrastructure.postgresql.project_types import PostgresProjectTypeGateway
from app.infrastructure.postgresql.property_store import read_values, write_value
from app.infrastructure.postgresql.schema import PostgresSchemaGateway


@pytest.fixture
def schema(authorized):
    return SchemaService(PostgresSchemaGateway(authorized.database, authorized.key, access=authorized.binding(4).access))


def templates(authorized):
    return ProjectTypeService(PostgresProjectTypeGateway(authorized.database, authorized.key, access=authorized.binding(4).access))


def test_schema_crud_preserves_flags_order_uniqueness_and_missing_records(schema, authorized):
    group = schema.create_group(' Group ', 1)
    assert schema.create_parameter(' p ', group, ' Property ', 'TEXT', True, ' Alias ', False, [1]) == 'p'
    row = schema.get_snapshot().parameters[0]
    assert (row.param_name, row.mandatory, row.alias, row.applies_to_all) == ('Property', True, 'Alias', False)
    assert schema.update_parameter('p', None, 'Updated', 'TEXT')
    assert templates(authorized).get_applicability('p').type_ids == (1,)
    assert schema.update_group(group, 'Updated', 3)
    assert schema.get_all_groups()[0].group_name == 'Updated'
    assert schema.get_next_available_group_order() == 1
    assert schema.generate_param_id() == 'PRM_001'
    for action, message in (
        (lambda: schema.create_parameter('p', None, 'Duplicate', 'TEXT'), 'ID'),
        (lambda: schema.create_group('Updated', 2), 'name'),
        (lambda: schema.create_group('Other', 3), 'order'),
    ):
        with pytest.raises(SchemaConflictError, match=message):
            action()
    assert not schema.update_parameter('missing', None, 'Missing', 'TEXT')
    with pytest.raises(ValueError, match='Unknown property'):
        schema.update_parameter('missing', None, 'Missing', 'TEXT', applies_to_all=True)
    assert not schema.update_group(999, 'Missing', 1)
    assert not schema.delete_group(999)
    assert not schema.delete_parameter('missing')
    assert not schema.delete_option(999)
    assert schema.delete_parameter('p')
    assert schema.delete_group(group)


def test_localized_aliases_are_separate_from_stable_codes_and_remove_when_blank(schema):
    schema.create_parameter('region', None, 'Region', 'TEXT', alias='Default')
    schema.set_alias_translation('region', ' FR ', ' Région ')
    schema.set_alias_translation('region', 'de-CH', 'Gebiet')
    assert schema.get_alias_translations(' Fr ') == {'region': 'Région'}
    assert schema.get_alias_translations('en') == {}
    schema.set_alias_translation('region', 'fr', 'Zone')
    assert schema.get_alias_translations('fr') == {'region': 'Zone'}
    assert schema.get_all_parameters()[0].alias == 'Default'
    schema.set_alias_translation('region', 'fr', ' ')
    assert schema.get_alias_translations('fr') == {}
    with pytest.raises(ValueError, match='language code'):
        schema.set_alias_translation('region', '../private', 'Bad')
    with pytest.raises(ValueError, match='Unknown property'):
        schema.set_alias_translation('missing', 'fr', 'Bad')
    schema.delete_parameter('region')
    assert schema.get_alias_translations('de-ch') == {}


def audit_count(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        return connection.execute('SELECT count(*) FROM eppm.app_security_audit').fetchone()[0]


def reject_mutation(authorized, table, event):
    # Only fixed table/event pairs from this test module reach the SQL identifiers.
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_schema_test() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private failure detail' USING ERRCODE='23514'; END $$""")
        connection.execute(f'CREATE TRIGGER reject_schema_test BEFORE {event} ON eppm.{table} '
                           'FOR EACH ROW EXECUTE FUNCTION eppm.reject_schema_test()')


def test_failed_initial_options_roll_back_definition_membership_and_audit(schema, authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_schema_test() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.option_value='Reject' THEN RAISE EXCEPTION 'private failure detail' USING ERRCODE='23514'; END IF;
            RETURN NEW; END $$""")
        connection.execute('CREATE TRIGGER reject_schema_test BEFORE INSERT ON eppm.schema_param_options FOR EACH ROW EXECUTE FUNCTION eppm.reject_schema_test()')
    before = audit_count(authorized)
    with pytest.raises(SchemaConflictError) as error:
        schema.create_parameter(None, None, 'Route', 'ENUM', applies_to_all=False, project_type_ids=[1], initial_options=['First', 'Reject'])
    assert 'private failure' not in str(error.value)
    assert schema.get_snapshot().parameters == schema.get_snapshot().options == []
    assert schema.generate_param_id() == 'PRM_001'
    assert authorized.query('SELECT param_id FROM eppm.project_type_property', user_id=4) == []
    assert audit_count(authorized) == before
    assert schema.create_parameter(None, None, 'Route', 'ENUM', initial_options=['First']) == 'PRM_001'
    assert audit_count(authorized) > before


def test_failed_applicability_change_restores_all_definition_details(schema, authorized):
    group = schema.create_group('Original', 1)
    schema.create_parameter('p', group, 'Original', 'TEXT', alias='Alias')
    before, count = schema.get_snapshot(), audit_count(authorized)
    with pytest.raises(SchemaConflictError):
        schema.update_parameter('p', None, 'Changed', 'TEXT', True, 'Changed', False, [1, 999])
    assert schema.get_snapshot() == before
    assert audit_count(authorized) == count
    assert templates(authorized).get_applicability('p').applies_to_all is True


@pytest.mark.parametrize('defaults', [False, True], ids=['project', 'template'])
@pytest.mark.parametrize('kind', ['ENUM', 'MULTI_ENUM'])
def test_scalar_and_list_references_protect_options_definitions_and_types(schema, authorized, defaults, kind):
    schema.create_parameter('p', None, 'Choice', kind, initial_options=['A'])
    option = schema.get_all_options()[0]
    value = ['A'] if kind == 'MULTI_ENUM' else 'A'
    authorized.database.run(lambda connection: write_value(connection, 1, 'p', value, defaults=defaults),
                            write=True, bind=authorized.binding(4))
    for action in (lambda: schema.delete_option(option.id), lambda: schema.delete_parameter(' p '),
                   lambda: schema.update_parameter('p', None, 'Changed', 'NUMBER')):
        with pytest.raises(ValueError):
            action()
    with psycopg.connect(authorized.setup.operator_url) as connection:
        table = 'project_type_property_default' if defaults else 'project_property_value'
        connection.execute(f'DELETE FROM eppm.{table} WHERE param_id=%s', ('p',))
    assert schema.delete_option(option.id)
    assert schema.update_parameter('p', None, 'Changed', 'NUMBER')
    assert schema.delete_parameter('p')


@pytest.mark.parametrize('defaults', [False, True])
def test_explicit_null_still_protects_the_definition(schema, authorized, defaults):
    schema.create_parameter('p', None, 'Nullable', 'TEXT')
    authorized.database.run(lambda connection: write_value(connection, 1, 'p', None, defaults=defaults),
                            write=True, bind=authorized.binding(4))
    with pytest.raises(ValueError, match='Clear stored values'):
        schema.update_parameter('p', None, 'Nullable', 'NUMBER')
    with pytest.raises(ValueError, match='stored values or defaults'):
        schema.delete_parameter('p')


def test_group_delete_preserves_values_and_rolls_back_ungrouping_on_failure(schema, authorized):
    group = schema.create_group('Group', 1)
    schema.create_parameter('p', group, 'Property', 'TEXT')
    authorized.database.run(lambda connection: write_value(connection, 1, 'p', 'Retained'), write=True, bind=authorized.binding(4))
    reject_mutation(authorized, 'schema_groups', 'DELETE')
    before = audit_count(authorized)
    with pytest.raises(SchemaConflictError):
        schema.delete_group(group)
    assert schema.get_all_parameters()[0].group_id == group
    assert audit_count(authorized) == before
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('DROP TRIGGER reject_schema_test ON eppm.schema_groups')
    assert schema.delete_group(group)
    assert schema.get_all_parameters()[0].group_id is None
    assert authorized.database.run(lambda connection: read_values(connection), bind=authorized.binding(4)) == {1: {'p': 'Retained'}}


def test_property_delete_restores_removed_choices_if_parent_delete_fails(schema, authorized):
    schema.create_parameter('p', None, 'Choice', 'ENUM', initial_options=['A', 'B'])
    before, count = schema.get_snapshot(), audit_count(authorized)
    reject_mutation(authorized, 'schema_parameters', 'DELETE')
    with pytest.raises(SchemaConflictError):
        schema.delete_parameter('p')
    assert schema.get_snapshot() == before
    assert audit_count(authorized) == count


def test_scoped_readers_get_label_references_but_cannot_administer_schema(schema, authorized):
    schema.create_parameter('region', None, 'Region', 'ENUM', alias='Area', initial_options=['North'])
    schema.set_alias_translation('region', 'fr', 'Région')
    reader = SchemaService(PostgresSchemaGateway(authorized.database, authorized.key, access=authorized.binding(1).access))
    assert [(row.param_id, row.alias) for row in reader.property_references()] == [('region', 'Area')]
    assert reader.alias_references(' FR ') == {'region': 'Région'}
    for action in (reader.get_snapshot, reader.get_all_groups, reader.get_all_options,
                   lambda: reader.create_parameter('bad', None, 'Denied', 'TEXT'),
                   lambda: reader.set_alias_translation('region', 'fr', 'Denied')):
        with pytest.raises(AccessDenied):
            action()
    for sql in ("UPDATE eppm.schema_parameters SET alias='Denied'",
                "INSERT INTO eppm.schema_parameter_translation VALUES ('region','fr','Denied') ON CONFLICT(param_id,locale) DO UPDATE SET alias=excluded.alias",
                'DELETE FROM eppm.schema_param_options'):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            authorized.query(sql, write=True)
    assert schema.get_alias_translations('fr') == {'region': 'Région'}


def test_deleted_choices_and_retyped_enum_properties_do_not_revive_old_grants(schema, authorized):
    schema.create_parameter('region', None, 'Region', 'ENUM', initial_options=['North', 'North'])
    old_option = schema.get_all_options()[0].id
    with psycopg.connect(authorized.setup.operator_url) as connection:
        old_scope = connection.execute("SELECT id FROM eppm.app_scope_property WHERE param_id='region'").fetchone()[0]
        grant = connection.execute("""INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
            VALUES (3,'project_viewer',%s,900,'test') RETURNING id""",
            (Jsonb({'kind': 'properties', 'conditions': [
                {'property_id': f'enum:{old_scope}', 'operator': 'eq', 'value_ids': [old_option]}
            ]}),)).fetchone()[0]
    assert schema.delete_option(old_option)
    assert schema.add_option('region', 'North', 1) > old_option
    assert schema.update_parameter('region', None, 'Region', 'TEXT')
    assert schema.update_parameter('region', None, 'Region', 'ENUM')
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT invalid_reason FROM eppm.app_role_assignment WHERE id=%s', (grant,)).fetchone()[0]
        assert connection.execute('SELECT param_id FROM eppm.app_scope_property WHERE id=%s', (old_scope,)).fetchone() == (None,)
        assert connection.execute("SELECT id FROM eppm.app_scope_property WHERE param_id='region'").fetchone()[0] > old_scope


@pytest.mark.parametrize('kind', ['parameter', 'group'])
def test_concurrent_auto_allocation_replays_with_fresh_identifiers_and_orders(schema, authorized, kind):
    barrier, attempts = Barrier(2), [0, 0]
    class GatedGateway(PostgresSchemaGateway):
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
    def create(index):
        service = SchemaService(GatedGateway(index))
        return (service.create_parameter(None, None, str(index), 'TEXT') if kind == 'parameter'
                else service.create_group(str(index), 1, auto_assign_order=True))
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(create, range(2)))
    if kind == 'parameter':
        assert set(result) == {'PRM_001', 'PRM_002'}
    else:
        assert len(set(result)) == 2
        assert [group.display_order for group in schema.get_all_groups()] == [1, 2]
    assert sum(attempts) >= 3


def test_schema_multi_query_snapshot_stays_consistent_during_compound_edit(schema, authorized):
    group = schema.create_group('Group', 1)
    schema.create_parameter('p', group, 'Original', 'ENUM', initial_options=['A'])
    started, changed = Event(), Event()
    gateway = PostgresSchemaGateway(authorized.database, authorized.key, access=authorized.binding(4).access)
    def read(store):
        groups = store.groups()
        started.set()
        assert changed.wait(10)
        return groups, store.parameters(), store.options()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(gateway.run, read, permission=Permission.SHARED)
        assert started.wait(10)
        try:
            schema.delete_group(group)
            schema.add_option('p', 'B', 2)
        finally:
            changed.set()
        groups, parameters, options = future.result()
    assert len(groups) == 1 and parameters[0].group_id == group
    assert [row.option_value for row in options] == ['A']
    assert schema.get_all_groups() == []
    assert len(schema.get_all_options()) == 2


def test_schema_outage_uses_safe_application_error(schema, authorized, caplog):
    authorized.database.close()
    with pytest.raises(SchemaStorageError) as error:
        schema.get_snapshot()
    assert 'postgresql://' not in str(error.value) + caplog.text


@pytest.mark.parametrize('kind', ['parameter', 'group'])
def test_auto_allocation_retries_when_competing_create_commits_after_snapshot(authorized, kind):
    ready, committed, attempts = Event(), Event(), [0]
    class DelayedGateway(PostgresSchemaGateway):
        def run(self, operation, **options):
            def callback(store):
                attempts[0] += 1
                if attempts[0] == 1:
                    ready.set()
                    assert committed.wait(10)
                return operation(store)
            return super().run(callback, **options)
    def create(gateway, name):
        service = SchemaService(gateway(authorized.database, authorized.key, access=authorized.binding(4).access))
        return (service.create_parameter(None, None, name, 'TEXT') if kind == 'parameter'
                else service.create_group(name, 1, auto_assign_order=True))
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(create, DelayedGateway, 'Second')
        assert ready.wait(10)
        try:
            first = create(PostgresSchemaGateway, 'First')
        finally:
            committed.set()
        second = future.result()
    assert first != second and attempts[0] >= 2


def test_option_deletion_racing_with_default_save_cannot_leave_invalid_selection(schema, authorized):
    schema.create_parameter('p', None, 'Choice', 'ENUM', initial_options=['A'])
    option = schema.get_all_options()[0].id
    barrier, attempts = Barrier(2), [0, 0]
    def gated(index, operation):
        def callback(store):
            attempts[index] += 1
            if attempts[index] == 1:
                barrier.wait(timeout=10)
            return operation(store)
        return callback
    class GatedSchemaGateway(PostgresSchemaGateway):
        def run(self, operation, **options):
            return super().run(gated(0, operation), **options)
    class GatedTypeGateway(PostgresProjectTypeGateway):
        def run(self, operation, **options):
            return super().run(gated(1, operation), **options)
    def operation(index):
        try:
            if index:
                service = ProjectTypeService(GatedTypeGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
                service.save_rule(1, 'p', has_default=True, default_value='A')
            else:
                service = SchemaService(GatedSchemaGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
                service.delete_option(option)
            return 'saved'
        except ValueError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(operation, range(2))) == ['conflict', 'saved']
    defaults = authorized.database.run(lambda connection: read_values(connection, defaults=True), bind=authorized.binding(4))
    assert not defaults or schema.get_all_options()[0].option_value == defaults[1]['p']
    assert sum(attempts) >= 3


def test_nullable_required_flag_is_exposed_as_false(schema, authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type,mandatory) VALUES ('p','Property','TEXT',NULL)")
    assert schema.get_all_parameters()[0].mandatory is False
    assert schema._gateway.run(lambda store: store.find_parameter('p'), permission=Permission.SHARED).mandatory is False


def test_retry_keeps_original_initial_options_and_applicability(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('CREATE SEQUENCE eppm.schema_attempt')
        connection.execute('GRANT USAGE ON SEQUENCE eppm.schema_attempt TO eppm_runtime')
        connection.execute("""CREATE FUNCTION eppm.retry_schema_once() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF nextval('eppm.schema_attempt')=1 THEN RAISE EXCEPTION 'Known rollback' USING ERRCODE='40001'; END IF;
            RETURN NEW; END $$""")
        connection.execute('CREATE TRIGGER retry_schema_once BEFORE INSERT ON eppm.schema_param_options FOR EACH ROW EXECUTE FUNCTION eppm.retry_schema_once()')
    submitted, type_ids, attempts = ['A'], [1], []
    class ChangedInputGateway(PostgresSchemaGateway):
        def run(self, operation, **options):
            def callback(store):
                attempts.append(1)
                if len(attempts) == 2:
                    submitted[:] = ['Changed']
                    type_ids[:] = [999]
                return operation(store)
            return super().run(callback, **options)
    service = SchemaService(ChangedInputGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    assert service.create_parameter(None, None, 'Choice', 'ENUM', applies_to_all=False,
                                    project_type_ids=type_ids, initial_options=submitted) == 'PRM_001'
    assert submitted == ['Changed'] and type_ids == [999] and len(attempts) == 2
    assert templates(authorized).get_applicability('PRM_001').type_ids == (1,)
    assert service.get_all_options()[0].option_value == 'A'
